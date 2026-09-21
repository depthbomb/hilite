use pyo3::exceptions::{PyIndexError, PyMemoryError, PyRuntimeError, PyTimeoutError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{PyString, PyTuple};
use std::collections::HashMap;
use std::ffi::{c_int, c_uint, c_void};
use std::ptr::NonNull;
use std::sync::{Arc, Mutex, OnceLock};
use std::time::{Duration, Instant};

type Captures = Arc<Vec<(i32, i32)>>;

struct RegexHandle(NonNull<c_void>);
struct Context(NonNull<c_void>);
// Handles own independent C allocations. Access is serialized by Mutex / PyO3's
// exclusive Line borrow. No process-global settings change after initialization.
unsafe impl Send for RegexHandle {}
unsafe impl Send for Context {}

#[pyclass(frozen, module = "hilite._oniguruma")]
struct Pattern {
    handle: Arc<Mutex<RegexHandle>>,
}

#[pyclass(frozen, module = "hilite._oniguruma")]
struct Scanner {
    patterns: Vec<Arc<Mutex<RegexHandle>>>,
}

struct Cached {
    _pattern: Arc<Mutex<RegexHandle>>,
    position: usize,
    match_start: usize,
    captures: Option<Captures>,
}

#[pyclass(module = "hilite._oniguruma")]
struct Line {
    text: Arc<str>,
    offsets: Vec<usize>,
    context: Mutex<Context>,
    cache: HashMap<(usize, u8), Cached>,
}

#[pyclass(frozen, module = "hilite._oniguruma")]
struct Match {
    text: Arc<str>,
    bytes: Captures,
    characters: Vec<(i32, i32)>,
    pattern: Arc<Mutex<RegexHandle>>,
}

unsafe extern "C" {
    fn hl_initialize() -> c_int;
    fn hl_compile(pattern: *const u8, length: c_int, error: *mut u8) -> *mut c_void;
    fn hl_free(regex: *mut c_void);
    fn hl_context_new() -> *mut c_void;
    fn hl_context_free(context: *mut c_void);
    fn hl_search(
        regex: *mut c_void,
        text: *const u8,
        length: c_int,
        start: c_int,
        flags: c_uint,
        context: *mut c_void,
    ) -> c_int;
    fn hl_capture_count(context: *mut c_void) -> c_int;
    fn hl_capture_start(context: *mut c_void, group: c_int) -> c_int;
    fn hl_capture_end(context: *mut c_void, group: c_int) -> c_int;
    fn hl_name_groups(
        regex: *mut c_void,
        name: *const u8,
        length: c_int,
        groups: *mut *mut c_int,
    ) -> c_int;
    fn hl_resource_error(status: c_int) -> c_int;
    fn hl_error(status: c_int, error: *mut u8);
}

static INITIALIZED: OnceLock<i32> = OnceLock::new();
static COMPILE_LOCK: Mutex<()> = Mutex::new(());

fn deadline(timeout: Option<f64>) -> PyResult<Option<Instant>> {
    match timeout {
        Some(seconds) if !seconds.is_finite() || seconds <= 0.0 => Err(PyTimeoutError::new_err(
            "highlighting exceeded its total deadline",
        )),
        Some(seconds) => Instant::now()
            .checked_add(
                Duration::try_from_secs_f64(seconds)
                    .map_err(|_| PyValueError::new_err("timeout is too large"))?,
            )
            .map(Some)
            .ok_or_else(|| PyValueError::new_err("timeout is too large")),
        None => Ok(None),
    }
}

fn check_deadline(deadline: Option<Instant>) -> PyResult<()> {
    if deadline.is_some_and(|end| Instant::now() >= end) {
        return Err(PyTimeoutError::new_err(
            "highlighting exceeded its total deadline",
        ));
    }
    Ok(())
}

fn error_message(buffer: &[u8]) -> String {
    let end = buffer
        .iter()
        .position(|byte| *byte == 0)
        .unwrap_or(buffer.len());
    String::from_utf8_lossy(&buffer[..end]).into_owned()
}

impl Drop for RegexHandle {
    fn drop(&mut self) {
        // SAFETY: this handle uniquely owns a successful hl_compile allocation.
        unsafe { hl_free(self.0.as_ptr()) };
    }
}

impl Drop for Context {
    fn drop(&mut self) {
        // SAFETY: this handle uniquely owns a successful hl_context_new allocation.
        unsafe { hl_context_free(self.0.as_ptr()) };
    }
}

#[pymethods]
impl Pattern {
    #[new]
    fn new(pattern: &str) -> PyResult<Self> {
        let length = i32::try_from(pattern.len())
            .map_err(|_| PyValueError::new_err("pattern exceeds Oniguruma's size limit"))?;
        // SAFETY: initialization runs exactly once, before any compile/search call.
        let status = *INITIALIZED.get_or_init(|| unsafe { hl_initialize() });
        if status != 0 {
            return Err(PyRuntimeError::new_err("Oniguruma initialization failed"));
        }
        let _guard = COMPILE_LOCK
            .lock()
            .map_err(|_| PyRuntimeError::new_err("compile lock poisoned"))?;
        let mut error = [0u8; 256];
        // SAFETY: pattern is valid UTF-8, its length fits int, and error has more
        // than ONIG_MAX_ERROR_MESSAGE_LEN bytes. The engine owns its compiled data.
        let pointer = unsafe { hl_compile(pattern.as_ptr(), length, error.as_mut_ptr()) };
        let handle =
            NonNull::new(pointer).ok_or_else(|| PyValueError::new_err(error_message(&error)))?;
        Ok(Self {
            handle: Arc::new(Mutex::new(RegexHandle(handle))),
        })
    }
}

#[pymethods]
impl Scanner {
    #[new]
    fn new(patterns: Vec<PyRef<'_, Pattern>>) -> Self {
        Self {
            patterns: patterns
                .iter()
                .map(|pattern| Arc::clone(&pattern.handle))
                .collect(),
        }
    }

    fn find(
        &self,
        mut line: PyRefMut<'_, Line>,
        position: usize,
        first: bool,
        anchored: bool,
        timeout: Option<f64>,
    ) -> PyResult<Option<(usize, Match)>> {
        let end = deadline(timeout)?;
        let start = line.byte_position(position)?;
        let flags = u8::from(first) | (u8::from(anchored) << 1);
        let mut best: Option<(usize, Captures)> = None;
        for (index, pattern) in self.patterns.iter().enumerate() {
            check_deadline(end)?;
            if let Some(captures) = line.search_cached(pattern, start, flags)? {
                let wins = best
                    .as_ref()
                    .is_none_or(|(_, prior)| captures[0].0 < prior[0].0);
                if wins {
                    let at_start = captures[0].0 as usize == start;
                    best = Some((index, captures));
                    if at_start {
                        // A match at the cursor wins; later patterns lose ties.
                        break;
                    }
                }
            }
        }
        check_deadline(end)?;
        best.map(|(index, captures)| {
            line.make_match(captures, &self.patterns[index])
                .map(|result| (index, result))
        })
        .transpose()
    }
}

impl Line {
    fn byte_position(&self, position: usize) -> PyResult<usize> {
        // ASCII byte offsets already match Python's character offsets.
        if self.offsets.is_empty() && position <= self.text.len() {
            return Ok(position);
        }
        self.offsets
            .get(position)
            .copied()
            .ok_or_else(|| PyIndexError::new_err("search position outside text"))
    }

    fn make_match(&self, captures: Captures, pattern: &Arc<Mutex<RegexHandle>>) -> PyResult<Match> {
        let mut characters = Vec::with_capacity(captures.len());
        for &(start, end) in captures.iter() {
            if start < 0 {
                characters.push((-1, -1));
            } else if self.offsets.is_empty() {
                characters.push((start, end));
            } else {
                let a = self.offsets.binary_search(&(start as usize));
                let b = self.offsets.binary_search(&(end as usize));
                let (a, b) = a.and_then(|a| b.map(|b| (a, b))).map_err(|_| {
                    PyRuntimeError::new_err("Oniguruma returned a non-character boundary")
                })?;
                characters.push((a as i32, b as i32));
            }
        }
        Ok(Match {
            text: Arc::clone(&self.text),
            bytes: captures,
            characters,
            pattern: Arc::clone(pattern),
        })
    }

    fn search_cached(
        &mut self,
        pattern: &Arc<Mutex<RegexHandle>>,
        position: usize,
        flags: u8,
    ) -> PyResult<Option<Captures>> {
        let key = (Arc::as_ptr(pattern) as usize, flags);
        // A live pattern is retained with each cache entry, preventing pointer reuse.
        if let Some(cached) = self.cache.get(&key) {
            // Anchored searches can depend on the cursor, so don't carry them forward.
            let reusable =
                flags & 2 == 0 && cached.position <= position && cached.match_start >= position;
            if reusable {
                return Ok(cached.captures.clone());
            }
        }
        let (captures, match_start) = {
            let regex = pattern
                .lock()
                .map_err(|_| PyRuntimeError::new_err("regex lock poisoned"))?;
            let context = self
                .context
                .get_mut()
                .map_err(|_| PyRuntimeError::new_err("context lock poisoned"))?;
            // SAFETY: both allocations are live and exclusively borrowed. Input is
            // valid UTF-8, int-sized, and position is a checked character boundary.
            let status = unsafe {
                hl_search(
                    regex.0.as_ptr(),
                    self.text.as_ptr(),
                    self.text.len() as i32,
                    position as i32,
                    flags.into(),
                    context.0.as_ptr(),
                )
            };
            if status == -1 {
                (None, usize::MAX)
            } else if status < -1 {
                let mut message = [0u8; 256];
                // SAFETY: error buffer is large enough and status came from Oniguruma.
                unsafe { hl_error(status, message.as_mut_ptr()) };
                if unsafe { hl_resource_error(status) } != 0 {
                    return Err(PyTimeoutError::new_err(format!(
                        "Oniguruma resource limit: {}",
                        error_message(&message)
                    )));
                }
                return Err(PyRuntimeError::new_err(error_message(&message)));
            } else {
                // SAFETY: a successful search initializes all region capture slots.
                let count = unsafe { hl_capture_count(context.0.as_ptr()) };
                let mut spans = Vec::with_capacity(count as usize);
                for group in 0..count {
                    spans.push(unsafe {
                        (
                            hl_capture_start(context.0.as_ptr(), group),
                            hl_capture_end(context.0.as_ptr(), group),
                        )
                    });
                }
                // Search returns the consumed start. Capture zero can start later
                // after \K and cannot establish whether a cached match is reusable.
                (Some(Arc::new(spans)), status as usize)
            }
        };
        if self.cache.len() < 2048 || self.cache.contains_key(&key) {
            self.cache.insert(
                key,
                Cached {
                    _pattern: Arc::clone(pattern),
                    position,
                    match_start,
                    captures: captures.clone(),
                },
            );
        }
        Ok(captures)
    }
}

#[pymethods]
impl Line {
    #[new]
    fn new(text: &str) -> PyResult<Self> {
        // Line is also usable directly without compiling a pattern first.
        let status = *INITIALIZED.get_or_init(|| unsafe { hl_initialize() });
        if status != 0 {
            return Err(PyRuntimeError::new_err("Oniguruma initialization failed"));
        }
        if text.len() > i32::MAX as usize {
            return Err(PyValueError::new_err("text exceeds Oniguruma's size limit"));
        }
        // SAFETY: allocation has no input pointers and is checked before use.
        let pointer = NonNull::new(unsafe { hl_context_new() })
            .ok_or_else(|| PyMemoryError::new_err("allocating Oniguruma search context"))?;
        let offsets = if text.is_ascii() {
            Vec::new()
        } else {
            text.char_indices()
                .map(|(offset, _)| offset)
                .chain(std::iter::once(text.len()))
                .collect()
        };
        Ok(Self {
            text: Arc::from(text),
            offsets,
            context: Mutex::new(Context(pointer)),
            cache: HashMap::new(),
        })
    }

    fn search(
        &mut self,
        pattern: &Pattern,
        position: usize,
        first: bool,
        anchored: bool,
        timeout: Option<f64>,
    ) -> PyResult<Option<Match>> {
        let end = deadline(timeout)?;
        let start = self.byte_position(position)?;
        let flags = u8::from(first) | (u8::from(anchored) << 1);
        let result = self.search_cached(&pattern.handle, start, flags)?;
        check_deadline(end)?;
        result
            .map(|captures| self.make_match(captures, &pattern.handle))
            .transpose()
    }
}

impl Match {
    fn group_index(&self, group: Option<&Bound<'_, PyAny>>) -> PyResult<usize> {
        let Some(group) = group else { return Ok(0) };
        let index = if let Ok(name) = group.cast::<PyString>() {
            let name = name.to_str()?;
            let handle = self
                .pattern
                .lock()
                .map_err(|_| PyRuntimeError::new_err("regex lock poisoned"))?;
            let mut groups = std::ptr::null_mut();
            // SAFETY: name lives for this call; returned group indices remain owned
            // by the locked compiled pattern and are read before releasing its lock.
            let count = unsafe {
                hl_name_groups(
                    handle.0.as_ptr(),
                    name.as_ptr(),
                    i32::try_from(name.len())
                        .map_err(|_| PyIndexError::new_err("group name too long"))?,
                    &mut groups,
                )
            };
            if count <= 0 {
                return Err(PyIndexError::new_err("no such group"));
            }
            let numbers = unsafe { std::slice::from_raw_parts(groups, count as usize) };
            *numbers
                .iter()
                .rev()
                .find(|&&number| self.bytes[number as usize].0 >= 0)
                .unwrap_or_else(|| numbers.last().unwrap()) as usize
        } else {
            group
                .extract::<usize>()
                .map_err(|_| PyIndexError::new_err("no such group"))?
        };
        if index >= self.bytes.len() {
            return Err(PyIndexError::new_err("no such group"));
        }
        Ok(index)
    }

    fn group_text(&self, index: usize) -> Option<&str> {
        let (start, end) = self.bytes[index];
        if start < 0 {
            None
        } else {
            self.text.get(start as usize..end as usize)
        }
    }
}

#[pymethods]
impl Match {
    #[pyo3(signature = (group=None))]
    fn start(&self, group: Option<&Bound<'_, PyAny>>) -> PyResult<i32> {
        Ok(self.characters[self.group_index(group)?].0)
    }

    #[pyo3(signature = (group=None))]
    fn end(&self, group: Option<&Bound<'_, PyAny>>) -> PyResult<i32> {
        Ok(self.characters[self.group_index(group)?].1)
    }

    #[pyo3(signature = (group=None))]
    fn group(&self, group: Option<&Bound<'_, PyAny>>) -> PyResult<Option<&str>> {
        Ok(self.group_text(self.group_index(group)?))
    }

    fn groups<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyTuple>> {
        PyTuple::new(
            py,
            (1..self.bytes.len()).map(|index| self.group_text(index)),
        )
    }
}

#[pymodule(gil_used = true)]
fn _oniguruma(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_class::<Pattern>()?;
    module.add_class::<Scanner>()?;
    module.add_class::<Line>()?;
    module.add_class::<Match>()?;
    module.add("ONIGURUMA_VERSION", "6.9.10")?;
    Ok(())
}
