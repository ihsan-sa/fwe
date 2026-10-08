# Bring-up firmware for an STM32G474 HRTIM boost converter (/fwe template).
# Vendor code is not copied in: FWE_CMSIS_CORE and FWE_CMSIS_DEVICE point at
# the pinned CMSIS trees under ~/.local/fwe-tools/src.
cmake_minimum_required(VERSION 3.20)
project(fw C ASM)

set(FWE_CMSIS_CORE "" CACHE PATH "CMSIS core tree (holds Include/core_cm4.h, or is that Include dir)")
set(FWE_CMSIS_DEVICE "" CACHE PATH "cmsis-device-g4 tree (Include/, Source/Templates/)")
set(FWE_VERSION "0.0.0" CACHE STRING "firmware version string")
set(FWE_STAGE "boost" CACHE STRING "firmware stage")

if(EXISTS "${FWE_CMSIS_CORE}/core_cm4.h")
  set(CMSIS_CORE_INC "${FWE_CMSIS_CORE}")
elseif(EXISTS "${FWE_CMSIS_CORE}/Include/core_cm4.h")
  set(CMSIS_CORE_INC "${FWE_CMSIS_CORE}/Include")
elseif(EXISTS "${FWE_CMSIS_CORE}/CMSIS/Core/Include/core_cm4.h")
  set(CMSIS_CORE_INC "${FWE_CMSIS_CORE}/CMSIS/Core/Include")
else()
  message(FATAL_ERROR "FWE_CMSIS_CORE='${FWE_CMSIS_CORE}' has no core_cm4.h")
endif()
set(CMSIS_DEV_INC "${FWE_CMSIS_DEVICE}/Include")
set(VENDOR_STARTUP "${FWE_CMSIS_DEVICE}/Source/Templates/gcc/startup_stm32g474xx.s")
set(VENDOR_SYSTEM "${FWE_CMSIS_DEVICE}/Source/Templates/system_stm32g4xx.c")
foreach(f "${CMSIS_DEV_INC}/stm32g474xx.h" "${VENDOR_STARTUP}" "${VENDOR_SYSTEM}")
  if(NOT EXISTS "${f}")
    message(FATAL_ERROR "FWE_CMSIS_DEVICE='${FWE_CMSIS_DEVICE}': missing ${f}")
  endif()
endforeach()

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_C_EXTENSIONS OFF)
set(CMAKE_EXECUTABLE_SUFFIX ".elf")

set(MCU_FLAGS -mcpu=cortex-m4 -mthumb -mfpu=fpv4-sp-d16 -mfloat-abi=hard)
set(LINKER_SCRIPT "${CMAKE_CURRENT_SOURCE_DIR}/ld/stm32g474xb.ld")

file(GLOB APP_SOURCES CONFIGURE_DEPENDS
  "${CMAKE_CURRENT_SOURCE_DIR}/src/*.c"
  "${CMAKE_CURRENT_SOURCE_DIR}/control/*.c")

add_executable(fw ${APP_SOURCES} "${VENDOR_STARTUP}" "${VENDOR_SYSTEM}")
target_include_directories(fw PRIVATE
  src control gen config "${CMSIS_CORE_INC}" "${CMSIS_DEV_INC}")
target_compile_definitions(fw PRIVATE
  STM32G474xx FW_VERSION="${FWE_VERSION}" FW_STAGE="${FWE_STAGE}")
target_compile_options(fw PRIVATE ${MCU_FLAGS} -Os -g
  -ffunction-sections -fdata-sections
  $<$<COMPILE_LANGUAGE:C>:-Wall -Wextra -Werror>)
target_link_options(fw PRIVATE ${MCU_FLAGS}
  -T${LINKER_SCRIPT} -Wl,--gc-sections -Wl,-Map=${CMAKE_CURRENT_BINARY_DIR}/fw.map
  -Wl,--print-memory-usage -Wl,--no-warn-rwx-segments --specs=nano.specs --specs=nosys.specs)
set_target_properties(fw PROPERTIES LINK_DEPENDS "${LINKER_SCRIPT}")
target_link_libraries(fw PRIVATE m)
# system_stm32g4xx.c builds clean under -Wall -Wextra -Werror with the pinned
# cmsis-device-g4 v1.2.6, so it gets the same warnings as our code. If a later
# pin trips them, silence that one vendor file (set_source_files_properties
# "${VENDOR_SYSTEM}" COMPILE_OPTIONS -w), never the whole build.

add_custom_command(TARGET fw POST_BUILD
  COMMAND ${CMAKE_OBJCOPY} -O binary $<TARGET_FILE:fw> ${CMAKE_CURRENT_BINARY_DIR}/fw.bin
  COMMAND ${CMAKE_OBJCOPY} -O ihex $<TARGET_FILE:fw> ${CMAKE_CURRENT_BINARY_DIR}/fw.hex
  COMMAND ${CMAKE_SIZE} $<TARGET_FILE:fw>
  BYPRODUCTS ${CMAKE_CURRENT_BINARY_DIR}/fw.bin ${CMAKE_CURRENT_BINARY_DIR}/fw.hex
             ${CMAKE_CURRENT_BINARY_DIR}/fw.map
  COMMENT "fw.elf -> fw.bin, fw.hex")
