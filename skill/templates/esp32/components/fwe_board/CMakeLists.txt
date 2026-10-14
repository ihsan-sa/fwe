# The board's pins as pinmap.py derives them (gen/board_pins.h), for our other components.
# The component is reached through a link in upstream/components, so resolve it first.
get_filename_component(fwe_board_dir "${CMAKE_CURRENT_LIST_DIR}" REALPATH)
idf_component_register(INCLUDE_DIRS "${fwe_board_dir}/../../gen")
