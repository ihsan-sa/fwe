# Template for our components: pure logic in core/ (host-tested), ESP-IDF glue beside it.
idf_component_register(SRCS "core/fwe_stub.c" "fwe_stub_idf.c"
                       INCLUDE_DIRS "include"
                       REQUIRES fwe_board log)
target_compile_options(${COMPONENT_LIB} PRIVATE -Wall -Wextra -Werror)
