# The phone web app. Only core/ so far; the HTTP server, the page and the NVS writes are the next step.
idf_component_register(SRCS "core/fwe_webapp.c"
                       INCLUDE_DIRS "include"
                       REQUIRES fwe_xover)
target_compile_options(${COMPONENT_LIB} PRIVATE -Wall -Wextra -Werror)
