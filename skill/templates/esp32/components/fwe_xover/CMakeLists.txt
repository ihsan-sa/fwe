# The sub crossover. Only core/ so far; the second I2S port and the delay line are the next step.
idf_component_register(SRCS "core/fwe_xover.c"
                       INCLUDE_DIRS "include")
target_compile_options(${COMPONENT_LIB} PRIVATE -Wall -Wextra -Werror)
