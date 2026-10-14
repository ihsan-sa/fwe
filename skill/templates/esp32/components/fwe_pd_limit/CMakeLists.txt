# The USB-PD power limiter. Only core/ so far; the CH224A I2C and rail ADC glue is the next step.
idf_component_register(SRCS "core/fwe_pd_limit.c"
                       INCLUDE_DIRS "include")
target_compile_options(${COMPONENT_LIB} PRIVATE -Wall -Wextra -Werror)
