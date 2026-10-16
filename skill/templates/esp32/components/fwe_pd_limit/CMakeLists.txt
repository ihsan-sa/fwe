# The USB-PD power limiter. Only core/ so far, which reads the CH224A through a register-read
# callback; the ESP-IDF glue (that callback on the I2C bus, the rail ADC) is the next step.
idf_component_register(SRCS "core/fwe_pd_limit.c"
                       INCLUDE_DIRS "include")
target_compile_options(${COMPONENT_LIB} PRIVATE -Wall -Wextra -Werror)
