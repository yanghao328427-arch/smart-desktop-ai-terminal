#include <cstdint>
#include <cstring>

#include "driver/i2s_pdm.h"
#include "esp_afe_sr_iface.h"
#include "esp_afe_sr_models.h"
#include "esp_check.h"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "model_path.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

namespace {

constexpr gpio_num_t kPdmClockPin = GPIO_NUM_42;
constexpr gpio_num_t kPdmDataPin = GPIO_NUM_41;
constexpr uint32_t kSampleRate = 16000;
constexpr char kWakeModelName[] = "wn9_nihaoxiaoxin_tts";

const char *kTag = "wakenet_probe";
i2s_chan_handle_t g_rx_channel = nullptr;
const esp_afe_sr_iface_t *g_afe = nullptr;
esp_afe_sr_data_t *g_afe_data = nullptr;

esp_err_t initialize_pdm_microphone() {
    i2s_chan_config_t channel_config = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_AUTO, I2S_ROLE_MASTER);
    ESP_RETURN_ON_ERROR(i2s_new_channel(&channel_config, nullptr, &g_rx_channel), kTag, "i2s_new_channel failed");

    i2s_pdm_rx_config_t pdm_config = {
        .clk_cfg = I2S_PDM_RX_CLK_DEFAULT_CONFIG(kSampleRate),
        .slot_cfg = I2S_PDM_RX_SLOT_DEFAULT_CONFIG(
            I2S_DATA_BIT_WIDTH_16BIT,
            I2S_SLOT_MODE_MONO
        ),
        .gpio_cfg = {
            .clk = kPdmClockPin,
            .din = kPdmDataPin,
            .invert_flags = {
                .clk_inv = false,
            },
        },
    };
    ESP_RETURN_ON_ERROR(i2s_channel_init_pdm_rx_mode(g_rx_channel, &pdm_config), kTag, "PDM RX init failed");
    return i2s_channel_enable(g_rx_channel);
}

void feed_task(void *) {
    const int feed_chunks = g_afe->get_feed_chunksize(g_afe_data);
    const int feed_channels = g_afe->get_feed_channel_num(g_afe_data);
    auto *samples = static_cast<int16_t *>(
        heap_caps_calloc(feed_chunks * feed_channels, sizeof(int16_t), MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT)
    );
    ESP_ERROR_CHECK(samples ? ESP_OK : ESP_ERR_NO_MEM);

    while (true) {
        size_t bytes_read = 0;
        ESP_ERROR_CHECK(i2s_channel_read(
            g_rx_channel,
            samples,
            feed_chunks * sizeof(int16_t),
            &bytes_read,
            portMAX_DELAY
        ));
        const size_t sample_count = bytes_read / sizeof(int16_t);
        for (int index = static_cast<int>(sample_count) - 1; index >= 0; --index) {
            samples[index * feed_channels] = samples[index];
            for (int channel = 1; channel < feed_channels; ++channel) {
                samples[index * feed_channels + channel] = 0;
            }
        }
        g_afe->feed(g_afe_data, samples);
    }
}

void detect_task(void *) {
    while (true) {
        afe_fetch_result_t *result = g_afe->fetch(g_afe_data);
        if (!result || result->ret_value != ESP_OK) {
            ESP_LOGE(kTag, "AFE fetch failed");
            continue;
        }
        if (result->wakeup_state == WAKENET_DETECTED) {
            ESP_LOGI(
                kTag,
                "WAKE_DETECTED model=%s word_id=%d model_index=%d volume=%.1f",
                kWakeModelName,
                result->wake_word_index,
                result->wakenet_model_index,
                result->data_volume
            );
            g_afe->disable_wakenet(g_afe_data);
            vTaskDelay(pdMS_TO_TICKS(1500));
            g_afe->enable_wakenet(g_afe_data);
            ESP_LOGI(kTag, "WAKE_REARMED");
        }
    }
}

}  // namespace

extern "C" void app_main() {
    ESP_LOGI(kTag, "starting WakeNet probe for 你好小鑫");
    ESP_ERROR_CHECK(initialize_pdm_microphone());

    srmodel_list_t *models = esp_srmodel_init("model");
    ESP_ERROR_CHECK(models ? ESP_OK : ESP_ERR_NOT_FOUND);

    afe_config_t *config = afe_config_init(
        "M",
        models,
        AFE_TYPE_SR,
        AFE_MODE_HIGH_PERF
    );
    ESP_ERROR_CHECK(config ? ESP_OK : ESP_ERR_NO_MEM);
    config->wakenet_init = true;
    config->vad_init = true;
    config->aec_init = false;
    config->ns_init = true;
    config->agc_init = true;

    g_afe = esp_afe_handle_from_config(config);
    ESP_ERROR_CHECK(g_afe ? ESP_OK : ESP_ERR_NOT_FOUND);
    g_afe_data = g_afe->create_from_config(config);
    ESP_ERROR_CHECK(g_afe_data ? ESP_OK : ESP_ERR_NO_MEM);
    afe_config_free(config);

    xTaskCreatePinnedToCore(feed_task, "wake_feed", 6144, nullptr, 5, nullptr, 0);
    xTaskCreatePinnedToCore(detect_task, "wake_detect", 8192, nullptr, 5, nullptr, 1);
}
