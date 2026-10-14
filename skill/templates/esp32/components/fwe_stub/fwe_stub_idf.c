#include "fwe_stub.h"

#include "esp_log.h"

#if __has_include("board_pins.h")
#include "board_pins.h"
#endif

static const char *TAG = "fwe_stub";

void fwe_stub_report(void)
{
#ifdef BOARD_ID
    ESP_LOGI(TAG, "board %s", BOARD_ID);
#else
    ESP_LOGI(TAG, "board unknown (no gen/board_pins.h)");
#endif
}
