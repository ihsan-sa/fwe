# The self-test console. Only core/ so far; the handlers (rails ADC, CH224A, DAC tone and PCM1863 loopback, network)
# and the USB serial and TCP glue are the next step.
idf_component_register(SRCS "core/fwe_selftest.c" "core/fwe_st_tone.c"
                       INCLUDE_DIRS "include")
target_compile_options(${COMPONENT_LIB} PRIVATE -Wall -Wextra -Werror)
