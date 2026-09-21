#include <stdlib.h>
#include "oniguruma.h"

typedef struct {
    OnigRegion* region;
    OnigMatchParam* params;
} HlContext;

int hl_initialize(void) {
    OnigEncoding encodings[] = {ONIG_ENCODING_UTF8};
    return onig_initialize(encodings, 1);
}

void* hl_compile(const unsigned char* pattern, int length, unsigned char* error) {
    OnigRegex regex = NULL;
    OnigErrorInfo info;
    int status = onig_new(&regex, pattern, pattern + length,
                         ONIG_OPTION_CAPTURE_GROUP, ONIG_ENCODING_UTF8,
                         ONIG_SYNTAX_DEFAULT, &info);
    if (status != ONIG_NORMAL) {
        onig_error_code_to_str(error, status, &info);
        return NULL;
    }
    return regex;
}

void hl_free(void* regex) {
    onig_free((OnigRegex)regex);
}

void* hl_context_new(void) {
    HlContext* context = (HlContext*)calloc(1, sizeof(HlContext));
    if (context == NULL) {
        return NULL;
    }
    context->region = onig_region_new();
    context->params = onig_new_match_param();
    if (context->region == NULL || context->params == NULL) {
        if (context->region != NULL) {
            onig_region_free(context->region, 1);
        }
        if (context->params != NULL) {
            onig_free_match_param(context->params);
        }
        free(context);
        return NULL;
    }
    onig_set_retry_limit_in_search_of_match_param(context->params, 10000000);
    onig_set_retry_limit_in_match_of_match_param(context->params, 10000000);
    onig_set_match_stack_limit_size_of_match_param(context->params, 1000000);
    return context;
}

void hl_context_free(void* pointer) {
    HlContext* context = (HlContext*)pointer;
    onig_region_free(context->region, 1);
    onig_free_match_param(context->params);
    free(context);
}

int hl_search(void* regex, const unsigned char* text, int length, int start,
              unsigned int flags, void* pointer) {
    HlContext* context = (HlContext*)pointer;
    OnigOptionType options = ONIG_OPTION_NONE;
    if (!(flags & 1)) {
        options |= ONIG_OPTION_NOT_BEGIN_STRING;
    }
    if (!(flags & 2)) {
        options |= ONIG_OPTION_NOT_BEGIN_POSITION;
    }
    return onig_search_with_param((OnigRegex)regex, text, text + length,
                                 text + start, text + length, context->region,
                                 options, context->params);
}

int hl_capture_count(void* pointer) {
    return ((HlContext*)pointer)->region->num_regs;
}

int hl_capture_start(void* pointer, int group) {
    return ((HlContext*)pointer)->region->beg[group];
}

int hl_capture_end(void* pointer, int group) {
    return ((HlContext*)pointer)->region->end[group];
}

int hl_name_groups(void* regex, const unsigned char* name, int length, int** groups) {
    return onig_name_to_group_numbers((OnigRegex)regex, name, name + length, groups);
}

int hl_resource_error(int status) {
    return status == ONIGERR_RETRY_LIMIT_IN_MATCH_OVER ||
           status == ONIGERR_RETRY_LIMIT_IN_SEARCH_OVER ||
           status == ONIGERR_MATCH_STACK_LIMIT_OVER ||
           status == ONIGERR_SUBEXP_CALL_LIMIT_IN_SEARCH_OVER;
}

void hl_error(int status, unsigned char* error) {
    onig_error_code_to_str(error, status);
}
