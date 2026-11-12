idf_component_register(SRCS "app_main.c" "tool_core.c" "board.c" "measure.c" "target_uart.c" "rpc.c" "network.c"
                       INCLUDE_DIRS "."
                       REQUIRES driver esp_timer esp_wifi esp_event esp_netif esp_http_server nvs_flash json esp_hw_support esp_psram)
