# The phone web app. core/ and the page (page/index.html) so far; the HTTP server serving them and the NVS writes are next.
# core/ also answers POST /api/selftest through fwe_selftest's core.
idf_component_register(SRCS "core/fwe_webapp.c"
                       INCLUDE_DIRS "include"
                       REQUIRES fwe_xover fwe_selftest)
target_compile_options(${COMPONENT_LIB} PRIVATE -Wall -Wextra -Werror)
