"""Component identification via fuzzy matching against a local component database."""

from __future__ import annotations

import difflib
import json
from pathlib import Path
from typing import Optional

from retrace.core.pipeline import Component

# ---------------------------------------------------------------------------
# Hardcoded component database — extends at runtime via learn_component()
# ---------------------------------------------------------------------------

LEARNED_DB_PATH: Path = Path.home() / ".local" / "share" / "retrace" / "learned_components.json"

_COMPONENT_DB: list[dict] = [
    # -----------------------------------------------------------------------
    # Microcontrollers — STM32 family
    # -----------------------------------------------------------------------
    {
        "part": "STM32F030C8T6",
        "aliases": ["STM32F030", "F030C8"],
        "category": "mcu",
        "manufacturer": "STMicroelectronics",
        "package": "LQFP48",
        "datasheet": "https://www.st.com/resource/en/datasheet/stm32f030c8.pdf",
        "description": "ARM Cortex-M0 48MHz, 64KB Flash",
    },
    {
        "part": "STM32F103C8T6",
        "aliases": ["STM32F103", "STM32", "103C8"],
        "category": "mcu",
        "manufacturer": "STMicroelectronics",
        "package": "LQFP48",
        "datasheet": "https://www.st.com/resource/en/datasheet/stm32f103c8.pdf",
        "description": "ARM Cortex-M3 32-bit MCU, 72MHz, 64KB Flash",
    },
    {
        "part": "STM32F205RGT6",
        "aliases": ["STM32F205", "F205RG"],
        "category": "mcu",
        "manufacturer": "STMicroelectronics",
        "package": "LQFP64",
        "datasheet": "https://www.st.com/resource/en/datasheet/stm32f205rg.pdf",
        "description": "ARM Cortex-M3 120MHz, 1MB Flash",
    },
    {
        "part": "STM32F303CCT6",
        "aliases": ["STM32F303", "F303CC"],
        "category": "mcu",
        "manufacturer": "STMicroelectronics",
        "package": "LQFP48",
        "datasheet": "https://www.st.com/resource/en/datasheet/stm32f303cc.pdf",
        "description": "ARM Cortex-M4 72MHz with FPU, DSP, 256KB Flash",
    },
    {
        "part": "STM32F411CEU6",
        "aliases": ["STM32F411", "F411CEU"],
        "category": "mcu",
        "manufacturer": "STMicroelectronics",
        "package": "UFQFPN48",
        "datasheet": "https://www.st.com/resource/en/datasheet/stm32f411ce.pdf",
        "description": "ARM Cortex-M4 84MHz, 512KB Flash",
    },
    {
        "part": "STM32F429ZIT6",
        "aliases": ["STM32F429", "F429ZI"],
        "category": "mcu",
        "manufacturer": "STMicroelectronics",
        "package": "LQFP144",
        "datasheet": "https://www.st.com/resource/en/datasheet/stm32f429zi.pdf",
        "description": "ARM Cortex-M4 180MHz, 2MB Flash, FMC, TFT",
    },
    {
        "part": "STM32F746NGH6",
        "aliases": ["STM32F746", "F746NG"],
        "category": "mcu",
        "manufacturer": "STMicroelectronics",
        "package": "TFBGA216",
        "datasheet": "https://www.st.com/resource/en/datasheet/stm32f746ng.pdf",
        "description": "ARM Cortex-M7 216MHz, 1MB Flash",
    },
    {
        "part": "STM32H743ZIT6",
        "aliases": ["STM32H743", "H743ZI"],
        "category": "mcu",
        "manufacturer": "STMicroelectronics",
        "package": "LQFP144",
        "datasheet": "https://www.st.com/resource/en/datasheet/stm32h743zi.pdf",
        "description": "ARM Cortex-M7 480MHz, 2MB Flash, DP-FPU",
    },
    {
        "part": "STM32L010C6T6",
        "aliases": ["STM32L010", "L010C6"],
        "category": "mcu",
        "manufacturer": "STMicroelectronics",
        "package": "LQFP48",
        "datasheet": "https://www.st.com/resource/en/datasheet/stm32l010c6.pdf",
        "description": "ARM Cortex-M0+ ultra-low-power, 32KB Flash",
    },
    {
        "part": "STM32L151CBT6",
        "aliases": ["STM32L151", "L151CB"],
        "category": "mcu",
        "manufacturer": "STMicroelectronics",
        "package": "LQFP48",
        "datasheet": "https://www.st.com/resource/en/datasheet/stm32l151cb.pdf",
        "description": "ARM Cortex-M3 ultra-low-power 32MHz, 128KB Flash",
    },
    {
        "part": "STM32L476RGT6",
        "aliases": ["STM32L476", "L476RG"],
        "category": "mcu",
        "manufacturer": "STMicroelectronics",
        "package": "LQFP64",
        "datasheet": "https://www.st.com/resource/en/datasheet/stm32l476rg.pdf",
        "description": "ARM Cortex-M4 80MHz ultra-low-power, 1MB Flash",
    },
    {
        "part": "STM32G031K8T6",
        "aliases": ["STM32G031", "G031K8"],
        "category": "mcu",
        "manufacturer": "STMicroelectronics",
        "package": "LQFP32",
        "datasheet": "https://www.st.com/resource/en/datasheet/stm32g031k8.pdf",
        "description": "ARM Cortex-M0+ 64MHz, 64KB Flash",
    },
    {
        "part": "STM32G474RET6",
        "aliases": ["STM32G474", "G474RE"],
        "category": "mcu",
        "manufacturer": "STMicroelectronics",
        "package": "LQFP64",
        "datasheet": "https://www.st.com/resource/en/datasheet/stm32g474re.pdf",
        "description": "ARM Cortex-M4 170MHz, HRTIM, 512KB Flash",
    },
    {
        "part": "STM32U575CIT6",
        "aliases": ["STM32U575", "U575CI"],
        "category": "mcu",
        "manufacturer": "STMicroelectronics",
        "package": "LQFP48",
        "datasheet": "https://www.st.com/resource/en/datasheet/stm32u575ci.pdf",
        "description": "ARM Cortex-M33 160MHz ultra-low-power, 2MB Flash",
    },
    {
        "part": "STM32WB55RGV6",
        "aliases": ["STM32WB55", "WB55RG"],
        "category": "mcu",
        "manufacturer": "STMicroelectronics",
        "package": "VFQFPN68",
        "datasheet": "https://www.st.com/resource/en/datasheet/stm32wb55rg.pdf",
        "description": "ARM Cortex-M4 + M0+ BLE/802.15.4 SoC, 1MB Flash",
    },
    {
        "part": "STM32WL55JCI6",
        "aliases": ["STM32WL55", "WL55JC"],
        "category": "mcu",
        "manufacturer": "STMicroelectronics",
        "package": "UFBGA73",
        "datasheet": "https://www.st.com/resource/en/datasheet/stm32wl55jc.pdf",
        "description": "ARM Cortex-M4 + M0+ LoRa/Sub-GHz SoC",
    },
    # -----------------------------------------------------------------------
    # Microcontrollers — ESP32 family
    # -----------------------------------------------------------------------
    {
        "part": "ESP32-WROOM-32",
        "aliases": ["ESP32", "ESP-WROOM", "WROOM32"],
        "category": "mcu",
        "manufacturer": "Espressif",
        "package": "Module",
        "datasheet": "https://www.espressif.com/sites/default/files/documentation/esp32-wroom-32_datasheet_en.pdf",
        "description": "Dual-core Xtensa 240MHz, WiFi+BT, 4MB Flash",
    },
    {
        "part": "ESP32-S2",
        "aliases": ["ESP32S2", "ESP32-S2-WROOM"],
        "category": "mcu",
        "manufacturer": "Espressif",
        "package": "Module",
        "datasheet": "https://www.espressif.com/sites/default/files/documentation/esp32-s2_datasheet_en.pdf",
        "description": "Xtensa LX7 240MHz, WiFi, USB OTG, 4MB Flash",
    },
    {
        "part": "ESP32-S3",
        "aliases": ["ESP32S3", "ESP32-S3-WROOM"],
        "category": "mcu",
        "manufacturer": "Espressif",
        "package": "Module",
        "datasheet": "https://www.espressif.com/sites/default/files/documentation/esp32-s3_datasheet_en.pdf",
        "description": "Dual-core Xtensa LX7 240MHz, WiFi+BT5, AI accelerator",
    },
    {
        "part": "ESP32-C3",
        "aliases": ["ESP32C3", "ESP32-C3-MINI"],
        "category": "mcu",
        "manufacturer": "Espressif",
        "package": "Module",
        "datasheet": "https://www.espressif.com/sites/default/files/documentation/esp32-c3_datasheet_en.pdf",
        "description": "RISC-V 160MHz, WiFi+BT5, 4MB Flash",
    },
    {
        "part": "ESP32-C6",
        "aliases": ["ESP32C6", "ESP32-C6-MINI"],
        "category": "mcu",
        "manufacturer": "Espressif",
        "package": "Module",
        "datasheet": "https://www.espressif.com/sites/default/files/documentation/esp32-c6_datasheet_en.pdf",
        "description": "RISC-V 160MHz, WiFi6+BT5+802.15.4, 4MB Flash",
    },
    {
        "part": "ESP32-H2",
        "aliases": ["ESP32H2"],
        "category": "mcu",
        "manufacturer": "Espressif",
        "package": "Module",
        "datasheet": "https://www.espressif.com/sites/default/files/documentation/esp32-h2_datasheet_en.pdf",
        "description": "RISC-V 96MHz, BT5+802.15.4 (Zigbee/Thread), no WiFi",
    },
    {
        "part": "ESP8266EX",
        "aliases": ["ESP8266", "ESP-12", "ESP-07"],
        "category": "mcu",
        "manufacturer": "Espressif",
        "package": "QFN32",
        "datasheet": "https://www.espressif.com/sites/default/files/documentation/0a-esp8266ex_datasheet_en.pdf",
        "description": "WiFi SoC, 80/160MHz, 802.11 b/g/n",
    },
    # -----------------------------------------------------------------------
    # Microcontrollers — AVR (ATmega / ATtiny)
    # -----------------------------------------------------------------------
    {
        "part": "ATmega328P",
        "aliases": ["ATmega328", "ATMEGA328P", "328P"],
        "category": "mcu",
        "manufacturer": "Microchip",
        "package": "TQFP32",
        "datasheet": "https://ww1.microchip.com/downloads/en/DeviceDoc/ATmega48A-PA-88A-PA-168A-PA-328-P-DS-DS40002061B.pdf",
        "description": "8-bit AVR, 20MHz, 32KB Flash",
    },
    {
        "part": "ATmega2560",
        "aliases": ["ATMEGA2560", "2560"],
        "category": "mcu",
        "manufacturer": "Microchip",
        "package": "TQFP100",
        "datasheet": "https://ww1.microchip.com/downloads/en/DeviceDoc/ATmega640-1280-1281-2560-2561-Datasheet-DS40002211A.pdf",
        "description": "8-bit AVR, 16MHz, 256KB Flash",
    },
    {
        "part": "ATmega32U4",
        "aliases": ["ATMEGA32U4", "32U4"],
        "category": "mcu",
        "manufacturer": "Microchip",
        "package": "TQFP44",
        "datasheet": "https://ww1.microchip.com/downloads/en/DeviceDoc/Atmel-7766-8-bit-AVR-ATmega16U4-32U4_Datasheet.pdf",
        "description": "8-bit AVR with native USB, 16MHz, 32KB Flash",
    },
    {
        "part": "ATtiny85",
        "aliases": ["ATTINY85", "TINY85"],
        "category": "mcu",
        "manufacturer": "Microchip",
        "package": "SOIC8",
        "datasheet": "https://ww1.microchip.com/downloads/en/DeviceDoc/Atmel-2586-AVR-8-bit-Microcontroller-ATtiny25-ATtiny45-ATtiny85_Datasheet.pdf",
        "description": "8-bit AVR, 20MHz, 8KB Flash, 8-pin",
    },
    {
        "part": "ATtiny84",
        "aliases": ["ATTINY84", "TINY84"],
        "category": "mcu",
        "manufacturer": "Microchip",
        "package": "SOIC14",
        "datasheet": "https://ww1.microchip.com/downloads/en/DeviceDoc/ATtiny24A-44A-84A-DataSheet-DS40002269A.pdf",
        "description": "8-bit AVR, 20MHz, 8KB Flash, 14-pin",
    },
    {
        "part": "ATtiny13",
        "aliases": ["ATTINY13", "TINY13"],
        "category": "mcu",
        "manufacturer": "Microchip",
        "package": "SOIC8",
        "datasheet": "https://ww1.microchip.com/downloads/en/DeviceDoc/Atmel-2535-AVR-ATtiny13_Datasheet.pdf",
        "description": "8-bit AVR, 20MHz, 1KB Flash, 8-pin",
    },
    # -----------------------------------------------------------------------
    # Microcontrollers — PIC
    # -----------------------------------------------------------------------
    {
        "part": "PIC16F877A",
        "aliases": ["PIC16F877", "16F877", "16F877A"],
        "category": "mcu",
        "manufacturer": "Microchip",
        "package": "PDIP40",
        "datasheet": "https://ww1.microchip.com/downloads/en/DeviceDoc/39582b.pdf",
        "description": "8-bit PIC, 20MHz, 14KB Flash",
    },
    {
        "part": "PIC18F4550",
        "aliases": ["PIC18F4550", "18F4550"],
        "category": "mcu",
        "manufacturer": "Microchip",
        "package": "PDIP40",
        "datasheet": "https://ww1.microchip.com/downloads/en/DeviceDoc/39632e.pdf",
        "description": "8-bit PIC with USB, 48MHz, 32KB Flash",
    },
    {
        "part": "PIC24FJ128GA010",
        "aliases": ["PIC24FJ", "24FJ128"],
        "category": "mcu",
        "manufacturer": "Microchip",
        "package": "TQFP100",
        "datasheet": "https://ww1.microchip.com/downloads/en/DeviceDoc/39747b.pdf",
        "description": "16-bit PIC, 32MHz, 128KB Flash",
    },
    # -----------------------------------------------------------------------
    # Microcontrollers — Other
    # -----------------------------------------------------------------------
    {
        "part": "RP2040",
        "aliases": ["RP2040", "RASPBERRY PI"],
        "category": "mcu",
        "manufacturer": "Raspberry Pi",
        "package": "QFN56",
        "datasheet": "https://datasheets.raspberrypi.com/rp2040/rp2040-datasheet.pdf",
        "description": "Dual Cortex-M0+, 133MHz, 264KB SRAM",
    },
    {
        "part": "nRF52832",
        "aliases": ["NRF52832", "NRF52"],
        "category": "mcu",
        "manufacturer": "Nordic Semiconductor",
        "package": "QFN48",
        "datasheet": "https://infocenter.nordicsemi.com/pdf/nRF52832_PS_v1.4.pdf",
        "description": "ARM Cortex-M4 64MHz, BLE5, 512KB Flash",
    },
    {
        "part": "nRF52840",
        "aliases": ["NRF52840"],
        "category": "mcu",
        "manufacturer": "Nordic Semiconductor",
        "package": "AQFN73",
        "datasheet": "https://infocenter.nordicsemi.com/pdf/nRF52840_PS_v1.1.pdf",
        "description": "ARM Cortex-M4 64MHz, BLE5+USB+802.15.4, 1MB Flash",
    },
    {
        "part": "nRF5340",
        "aliases": ["NRF5340"],
        "category": "mcu",
        "manufacturer": "Nordic Semiconductor",
        "package": "AQFN94",
        "datasheet": "https://infocenter.nordicsemi.com/pdf/nRF5340_PS_v1.3.pdf",
        "description": "Dual-core Cortex-M33, BLE5.3+802.15.4, 1MB Flash",
    },
    {
        "part": "CC2652R",
        "aliases": ["CC2652", "CC2652R"],
        "category": "mcu",
        "manufacturer": "Texas Instruments",
        "package": "VQFN48",
        "datasheet": "https://www.ti.com/lit/ds/symlink/cc2652r.pdf",
        "description": "ARM Cortex-M4 48MHz, multi-protocol (BLE/Zigbee/Thread)",
    },
    {
        "part": "MSP430G2553",
        "aliases": ["MSP430", "MSP430G2", "G2553"],
        "category": "mcu",
        "manufacturer": "Texas Instruments",
        "package": "PDIP20",
        "datasheet": "https://www.ti.com/lit/ds/symlink/msp430g2553.pdf",
        "description": "16-bit ultra-low-power, 16MHz, 16KB Flash",
    },
    {
        "part": "ATSAMD21G18A",
        "aliases": ["SAMD21", "SAM D21", "SAMD21G18"],
        "category": "mcu",
        "manufacturer": "Microchip",
        "package": "TQFP48",
        "datasheet": "https://ww1.microchip.com/downloads/en/DeviceDoc/SAM-D21DA1-Family-Data-Sheet-DS40001882G.pdf",
        "description": "ARM Cortex-M0+ 48MHz, 256KB Flash, USB",
    },
    {
        "part": "ATSAME70Q21B",
        "aliases": ["SAME70", "SAM E70"],
        "category": "mcu",
        "manufacturer": "Microchip",
        "package": "LQFP144",
        "datasheet": "https://ww1.microchip.com/downloads/en/DeviceDoc/SAM-E70-S70-V70-V71-Family-Data-Sheet-DS60001527E.pdf",
        "description": "ARM Cortex-M7 300MHz, 2MB Flash, EtherMAC",
    },
    {
        "part": "GD32F103CBT6",
        "aliases": ["GD32F103", "GD32"],
        "category": "mcu",
        "manufacturer": "GigaDevice",
        "package": "LQFP48",
        "datasheet": "https://www.gigadevice.com/datasheet/gd32f103xx-datasheet/",
        "description": "ARM Cortex-M3 108MHz, 128KB Flash (STM32 clone)",
    },
    {
        "part": "CC2540",
        "aliases": ["CC2540", "CC2540F256"],
        "category": "mcu",
        "manufacturer": "Texas Instruments",
        "package": "QFN40",
        "datasheet": "https://www.ti.com/lit/ds/symlink/cc2540.pdf",
        "description": "8051 BLE SoC, 32MHz, 256KB Flash",
    },
    {
        "part": "CC2530",
        "aliases": ["CC2530", "CC2530F256"],
        "category": "rf",
        "manufacturer": "Texas Instruments",
        "package": "QFN40",
        "datasheet": "https://www.ti.com/lit/ds/symlink/cc2530.pdf",
        "description": "ZigBee/IEEE 802.15.4 SoC",
    },
    # -----------------------------------------------------------------------
    # Voltage regulators — LDO linear
    # -----------------------------------------------------------------------
    {
        "part": "LM7805",
        "aliases": ["7805", "L7805", "LM7805CT"],
        "category": "regulator",
        "manufacturer": "Texas Instruments",
        "package": "TO-220",
        "datasheet": "https://www.ti.com/lit/ds/symlink/lm7805.pdf",
        "description": "1A linear regulator, 5V fixed output",
    },
    {
        "part": "LM7812",
        "aliases": ["7812", "L7812"],
        "category": "regulator",
        "manufacturer": "Texas Instruments",
        "package": "TO-220",
        "datasheet": "https://www.ti.com/lit/ds/symlink/lm7812.pdf",
        "description": "1A linear regulator, 12V fixed output",
    },
    {
        "part": "L7833",
        "aliases": ["7833", "L7833CV", "L7833ABV"],
        "category": "regulator",
        "manufacturer": "STMicroelectronics",
        "package": "TO-220",
        "datasheet": "https://www.st.com/resource/en/datasheet/l78.pdf",
        "description": "1A linear regulator, 3.3V fixed output",
    },
    {
        "part": "LM317T",
        "aliases": ["LM317", "LM317L"],
        "category": "regulator",
        "manufacturer": "Texas Instruments",
        "package": "TO-220",
        "datasheet": "https://www.ti.com/lit/ds/symlink/lm317.pdf",
        "description": "1.5A adjustable LDO, 1.25V–37V",
    },
    {
        "part": "LM1117-3.3",
        "aliases": ["LM1117", "LM1117T", "LD1117"],
        "category": "regulator",
        "manufacturer": "Texas Instruments",
        "package": "SOT-223",
        "datasheet": "https://www.ti.com/lit/ds/symlink/lm1117.pdf",
        "description": "800mA LDO, 3.3V output",
    },
    {
        "part": "LM1117-5.0",
        "aliases": ["LM1117-5", "LD1117-5"],
        "category": "regulator",
        "manufacturer": "Texas Instruments",
        "package": "SOT-223",
        "datasheet": "https://www.ti.com/lit/ds/symlink/lm1117.pdf",
        "description": "800mA LDO, 5.0V output",
    },
    {
        "part": "AMS1117-3.3",
        "aliases": ["AMS1117", "AMS1117-3.3", "AMS117"],
        "category": "regulator",
        "manufacturer": "Advanced Monolithic Systems",
        "package": "SOT-223",
        "datasheet": "http://www.advanced-monolithic.com/pdf/ds1117.pdf",
        "description": "1A LDO, adjustable/fixed 1.5V–5V",
    },
    {
        "part": "AMS1117-1.8",
        "aliases": ["AMS1117-1.8", "AMS117-1.8"],
        "category": "regulator",
        "manufacturer": "Advanced Monolithic Systems",
        "package": "SOT-223",
        "datasheet": "http://www.advanced-monolithic.com/pdf/ds1117.pdf",
        "description": "1A LDO, 1.8V fixed output",
    },
    {
        "part": "AP2112K-3.3",
        "aliases": ["AP2112", "AP2112K"],
        "category": "regulator",
        "manufacturer": "Diodes Inc",
        "package": "SOT-25",
        "datasheet": "https://www.diodes.com/assets/Datasheets/AP2112.pdf",
        "description": "600mA LDO, 3.3V, CMOS low dropout",
    },
    {
        "part": "TPS7A3301DGNR",
        "aliases": ["TPS7A33", "TPS7A3301"],
        "category": "regulator",
        "manufacturer": "Texas Instruments",
        "package": "MSOP-8",
        "datasheet": "https://www.ti.com/lit/ds/symlink/tps7a33.pdf",
        "description": "100mA ultra-low-noise LDO, adjustable",
    },
    {
        "part": "MCP1700T-3302E",
        "aliases": ["MCP1700", "MCP1700T"],
        "category": "regulator",
        "manufacturer": "Microchip",
        "package": "SOT-23",
        "datasheet": "https://ww1.microchip.com/downloads/en/DeviceDoc/20001826D.pdf",
        "description": "250mA low quiescent LDO, 3.3V",
    },
    {
        "part": "NCV8114ASN330T1G",
        "aliases": ["NCV8114", "NCV8114A"],
        "category": "regulator",
        "manufacturer": "onsemi",
        "package": "SOT-23-5",
        "datasheet": "https://www.onsemi.com/pdf/datasheet/ncv8114a-d.pdf",
        "description": "150mA LDO, 3.3V, low noise",
    },
    {
        "part": "RT9013-33GB",
        "aliases": ["RT9013", "RT9013-33"],
        "category": "regulator",
        "manufacturer": "Richtek",
        "package": "SOT-23-5",
        "datasheet": "https://www.richtek.com/assets/product_file/RT9013/DS9013-08.pdf",
        "description": "500mA LDO, 3.3V, low noise",
    },
    {
        "part": "SPX3819M5-L-3-3",
        "aliases": ["SPX3819", "SPX3819M5"],
        "category": "regulator",
        "manufacturer": "MaxLinear",
        "package": "SOT-23-5",
        "datasheet": "https://www.maxlinear.com/ds/spx3819.pdf",
        "description": "500mA LDO, 3.3V fixed",
    },
    {
        "part": "TLV1117-33IDCYR",
        "aliases": ["TLV1117", "TLV1117-33"],
        "category": "regulator",
        "manufacturer": "Texas Instruments",
        "package": "SOT-223",
        "datasheet": "https://www.ti.com/lit/ds/symlink/tlv1117.pdf",
        "description": "800mA LDO, 3.3V, TI enhanced 1117",
    },
    # -----------------------------------------------------------------------
    # Voltage regulators — Switching (buck/boost)
    # -----------------------------------------------------------------------
    {
        "part": "MP2315",
        "aliases": ["MP2315", "MP2315GJ"],
        "category": "regulator",
        "manufacturer": "Monolithic Power Systems",
        "package": "TSOT23-8",
        "datasheet": "https://www.monolithicpower.com/pub/media/document/MP2315_r1.0.pdf",
        "description": "3A high-efficiency buck converter",
    },
    {
        "part": "TPS62160DSGR",
        "aliases": ["TPS62160", "TPS6216"],
        "category": "power",
        "manufacturer": "Texas Instruments",
        "package": "WSON-8",
        "datasheet": "https://www.ti.com/lit/ds/symlink/tps62160.pdf",
        "description": "1A step-down converter, 3–17V input",
    },
    {
        "part": "TPS63020DSJR",
        "aliases": ["TPS63020"],
        "category": "power",
        "manufacturer": "Texas Instruments",
        "package": "VSON-10",
        "datasheet": "https://www.ti.com/lit/ds/symlink/tps63020.pdf",
        "description": "2A buck-boost converter, Li-ion range",
    },
    {
        "part": "LTC3780EG",
        "aliases": ["LTC3780"],
        "category": "power",
        "manufacturer": "Analog Devices",
        "package": "SSOP28",
        "datasheet": "https://www.analog.com/media/en/technical-documentation/data-sheets/3780fb.pdf",
        "description": "High-efficiency synchronous buck-boost, 4–30V",
    },
    {
        "part": "MP1584EN",
        "aliases": ["MP1584", "MP1584EN"],
        "category": "power",
        "manufacturer": "Monolithic Power Systems",
        "package": "SOIC8",
        "datasheet": "https://www.monolithicpower.com/pub/media/document/MP1584_r1.0.pdf",
        "description": "3A buck converter, 4.5–28V input",
    },
    {
        "part": "MP2307DN",
        "aliases": ["MP2307"],
        "category": "power",
        "manufacturer": "Monolithic Power Systems",
        "package": "SOIC8",
        "datasheet": "https://www.monolithicpower.com/pub/media/document/MP2307_r1.9.pdf",
        "description": "3A 23V synchronous rectified step-down",
    },
    {
        "part": "RT8059GJ5",
        "aliases": ["RT8059"],
        "category": "power",
        "manufacturer": "Richtek",
        "package": "SOT-23-5",
        "datasheet": "https://www.richtek.com/assets/product_file/RT8059/DS8059-02.pdf",
        "description": "1.5A PWM buck converter, 0.6V–Vin output",
    },
    {
        "part": "SY8089AAAC",
        "aliases": ["SY8089"],
        "category": "power",
        "manufacturer": "Silergy",
        "package": "SOT-23-5",
        "datasheet": "https://www.silergy.com/download/SY8089A.pdf",
        "description": "2A synchronous buck converter, 1MHz",
    },
    {
        "part": "AP3418KTR-G1",
        "aliases": ["AP3418"],
        "category": "power",
        "manufacturer": "Diodes Inc",
        "package": "SOT-23-6",
        "datasheet": "https://www.diodes.com/assets/Datasheets/AP3418.pdf",
        "description": "1.2A synchronous buck converter",
    },
    {
        "part": "TPS54331DR",
        "aliases": ["TPS54331"],
        "category": "power",
        "manufacturer": "Texas Instruments",
        "package": "SOIC8",
        "datasheet": "https://www.ti.com/lit/ds/symlink/tps54331.pdf",
        "description": "3A 28V input synchronous buck converter",
    },
    {
        "part": "LM2596S-5.0",
        "aliases": ["LM2596", "LM2596S"],
        "category": "power",
        "manufacturer": "Texas Instruments",
        "package": "TO-263-5",
        "datasheet": "https://www.ti.com/lit/ds/symlink/lm2596.pdf",
        "description": "3A step-down voltage regulator, 5V fixed",
    },
    # -----------------------------------------------------------------------
    # USB / Interface ICs
    # -----------------------------------------------------------------------
    {
        "part": "CH340G",
        "aliases": ["CH340", "CH340G"],
        "category": "usb",
        "manufacturer": "WCH",
        "package": "SOP16",
        "datasheet": "https://www.wch-ic.com/downloads/CH340DS1_PDF.html",
        "description": "USB-to-UART bridge",
    },
    {
        "part": "CH340C",
        "aliases": ["CH340C"],
        "category": "usb",
        "manufacturer": "WCH",
        "package": "SOP16",
        "datasheet": "https://www.wch-ic.com/downloads/CH340DS1_PDF.html",
        "description": "USB-to-UART with internal crystal",
    },
    {
        "part": "CH340K",
        "aliases": ["CH340K"],
        "category": "usb",
        "manufacturer": "WCH",
        "package": "ESSOP10",
        "datasheet": "https://www.wch-ic.com/downloads/CH340DS1_PDF.html",
        "description": "USB-to-UART compact package",
    },
    {
        "part": "FT232RL",
        "aliases": ["FT232", "FT232R", "FTDI"],
        "category": "usb",
        "manufacturer": "FTDI",
        "package": "SSOP28",
        "datasheet": "https://ftdichip.com/wp-content/uploads/2020/08/DS_FT232R.pdf",
        "description": "USB-to-UART/FIFO, 3Mbaud",
    },
    {
        "part": "FT2232H",
        "aliases": ["FT2232", "FT2232H"],
        "category": "usb",
        "manufacturer": "FTDI",
        "package": "LQFP64",
        "datasheet": "https://ftdichip.com/wp-content/uploads/2020/07/DS_FT2232H.pdf",
        "description": "Dual USB HS UART/FIFO/SPI/I2C/JTAG adapter",
    },
    {
        "part": "FT4232H",
        "aliases": ["FT4232", "FT4232H"],
        "category": "usb",
        "manufacturer": "FTDI",
        "package": "LQFP64",
        "datasheet": "https://ftdichip.com/wp-content/uploads/2020/07/DS_FT4232H.pdf",
        "description": "Quad USB HS UART adapter",
    },
    {
        "part": "CP2102N",
        "aliases": ["CP2102", "CP210X", "CP2102N"],
        "category": "usb",
        "manufacturer": "Silicon Labs",
        "package": "QFN28",
        "datasheet": "https://www.silabs.com/documents/public/data-sheets/CP2102-9.pdf",
        "description": "USB-to-UART single chip bridge",
    },
    {
        "part": "CP2104",
        "aliases": ["CP2104"],
        "category": "usb",
        "manufacturer": "Silicon Labs",
        "package": "QFN24",
        "datasheet": "https://www.silabs.com/documents/public/data-sheets/cp2104.pdf",
        "description": "Single-chip USB-to-UART with 4 GPIO",
    },
    {
        "part": "MAX3232ECPWR",
        "aliases": ["MAX3232", "MAX232"],
        "category": "usb",
        "manufacturer": "Maxim",
        "package": "TSSOP16",
        "datasheet": "https://datasheets.maximintegrated.com/en/ds/MAX3222-MAX3241.pdf",
        "description": "3V RS-232 transceiver, 2 TX / 2 RX",
    },
    {
        "part": "MAX232CPE",
        "aliases": ["MAX232CPE", "MAX232E"],
        "category": "usb",
        "manufacturer": "Maxim",
        "package": "PDIP16",
        "datasheet": "https://datasheets.maximintegrated.com/en/ds/MAX220-MAX249.pdf",
        "description": "5V RS-232 transceiver with internal charge pump",
    },
    # -----------------------------------------------------------------------
    # Memory — SPI Flash
    # -----------------------------------------------------------------------
    {
        "part": "W25Q128JV",
        "aliases": ["W25Q128", "25Q128", "WINBOND"],
        "category": "flash",
        "manufacturer": "Winbond",
        "package": "SOP8",
        "datasheet": "https://www.winbond.com/resource-files/w25q128jv%20revf%2003272018%20plus.pdf",
        "description": "128Mbit SPI NOR Flash",
    },
    {
        "part": "W25Q64JV",
        "aliases": ["W25Q64", "25Q64"],
        "category": "flash",
        "manufacturer": "Winbond",
        "package": "SOP8",
        "datasheet": "https://www.winbond.com/resource-files/w25q64jv%20revj%2003272018%20plus.pdf",
        "description": "64Mbit SPI NOR Flash",
    },
    {
        "part": "W25Q32JV",
        "aliases": ["W25Q32", "25Q32"],
        "category": "flash",
        "manufacturer": "Winbond",
        "package": "SOP8",
        "datasheet": "https://www.winbond.com/resource-files/w25q32jv%20revg%2003272018%20plus.pdf",
        "description": "32Mbit SPI NOR Flash",
    },
    {
        "part": "AT25SF128A",
        "aliases": ["AT25SF128", "AT25SF"],
        "category": "flash",
        "manufacturer": "Adesto",
        "package": "SOP8",
        "datasheet": "https://www.adestotech.com/wp-content/uploads/DS-AT25SF128A_047.pdf",
        "description": "128Mbit SPI Flash, industrial grade",
    },
    {
        "part": "MX25L12835F",
        "aliases": ["MX25L128", "MX25L12835"],
        "category": "flash",
        "manufacturer": "Macronix",
        "package": "SOP8",
        "datasheet": "https://www.macronix.com/Lists/Datasheet/Attachments/7395/MX25L12835F,%203V,%20128Mb,%20v1.6.pdf",
        "description": "128Mbit SPI NOR Flash, 3V",
    },
    {
        "part": "SST25VF016B",
        "aliases": ["SST25VF016", "SST25"],
        "category": "flash",
        "manufacturer": "Microchip",
        "package": "SOP8",
        "datasheet": "https://ww1.microchip.com/downloads/en/DeviceDoc/S71271_04.pdf",
        "description": "16Mbit SPI Serial Flash",
    },
    {
        "part": "GD25Q64",
        "aliases": ["GD25Q64", "25Q64GD"],
        "category": "flash",
        "manufacturer": "GigaDevice",
        "package": "SOP8",
        "datasheet": "https://www.gigadevice.com/datasheet/gd25q64c/",
        "description": "64Mbit SPI NOR Flash",
    },
    {
        "part": "IS25LP128F",
        "aliases": ["IS25LP128", "IS25LP"],
        "category": "flash",
        "manufacturer": "ISSI",
        "package": "SOP8",
        "datasheet": "https://www.issi.com/WW/pdf/IS25LP128F.pdf",
        "description": "128Mbit SPI NOR Flash, 133MHz",
    },
    {
        "part": "S25FL256SAGMFI001",
        "aliases": ["S25FL256", "S25FL256L"],
        "category": "flash",
        "manufacturer": "Infineon",
        "package": "SOP8",
        "datasheet": "https://www.infineon.com/dgdl/Infineon-S25FL256L-DataSheet-v05_00-EN.pdf",
        "description": "256Mbit SPI NOR Flash",
    },
    # -----------------------------------------------------------------------
    # Memory — EEPROM (I2C)
    # -----------------------------------------------------------------------
    {
        "part": "AT24C256",
        "aliases": ["AT24C256", "24C256"],
        "category": "eeprom",
        "manufacturer": "Microchip",
        "package": "SOIC8",
        "datasheet": "https://ww1.microchip.com/downloads/en/DeviceDoc/doc0670.pdf",
        "description": "256Kbit I2C EEPROM",
    },
    {
        "part": "AT24C02",
        "aliases": ["AT24C02", "24C02"],
        "category": "eeprom",
        "manufacturer": "Microchip",
        "package": "SOIC8",
        "datasheet": "https://ww1.microchip.com/downloads/en/DeviceDoc/doc0180.pdf",
        "description": "2Kbit I2C EEPROM, 1M erase/write",
    },
    # -----------------------------------------------------------------------
    # RF & Wireless
    # -----------------------------------------------------------------------
    {
        "part": "nRF24L01",
        "aliases": ["NRF24L01", "NRF24", "24L01"],
        "category": "rf",
        "manufacturer": "Nordic Semiconductor",
        "package": "QFN20",
        "datasheet": "https://infocenter.nordicsemi.com/pdf/nRF24L01P_PS_v1.0.pdf",
        "description": "2.4GHz RF transceiver, -6dBm to 0dBm",
    },
    {
        "part": "CC1101",
        "aliases": ["CC1101"],
        "category": "rf",
        "manufacturer": "Texas Instruments",
        "package": "QFN20",
        "datasheet": "https://www.ti.com/lit/ds/symlink/cc1101.pdf",
        "description": "Sub-1GHz RF transceiver, 315/433/868/915 MHz",
    },
    {
        "part": "SX1276MB1MAS",
        "aliases": ["SX1276", "SX1276MB"],
        "category": "rf",
        "manufacturer": "Semtech",
        "package": "TQFN28",
        "datasheet": "https://semtech.my.salesforce.com/sfc/p/#E0000000JelG/a/2R000000HT76/7Nka9W5WgugoZe.xwIHJy6ebj1hW8UJ.CSjV7p3nSyw",
        "description": "LoRa 868/915 MHz transceiver",
    },
    {
        "part": "SX1262",
        "aliases": ["SX1262"],
        "category": "rf",
        "manufacturer": "Semtech",
        "package": "HCLGA24",
        "datasheet": "https://semtech.my.salesforce.com/sfc/p/#E0000000JelG/a/2R000000Un7F/bOssk1oDB7V.pXj1sEKR_T8G0gQSrGXxFcVSxX2WEJM",
        "description": "LoRa 868/915 MHz next-gen transceiver",
    },
    {
        "part": "RTL8720DN",
        "aliases": ["RTL8720D", "RTL8720DN"],
        "category": "rf",
        "manufacturer": "Realtek",
        "package": "QFN48",
        "datasheet": "https://www.realtek.com/en/products/wireless-lan-ics/item/rtl8720dn",
        "description": "Dual-band WiFi5+BT5 combo, ARM Cortex-M33+M0",
    },
    {
        "part": "CYW43455",
        "aliases": ["CYW43455", "BCM43455"],
        "category": "rf",
        "manufacturer": "Infineon",
        "package": "WLBGA",
        "datasheet": "https://www.infineon.com/cms/en/product/wireless-connectivity/airoc-wi-fi-plus-bluetooth-combos/cyw43455/",
        "description": "WiFi5+BT5 combo (Raspberry Pi CM4/Zero2W)",
    },
    {
        "part": "MT7688AN",
        "aliases": ["MT7688", "MT7688AN"],
        "category": "rf",
        "manufacturer": "MediaTek",
        "package": "QFN88",
        "datasheet": "https://labs.mediatek.com/fileMedia/download/9ef51e98-49b1-489a-b27e-391bac9f7bf3",
        "description": "MIPS 580MHz WiFi SoC, 802.11n",
    },
    {
        "part": "ATWILC1000B-MU",
        "aliases": ["ATWILC1000", "WILC1000"],
        "category": "rf",
        "manufacturer": "Microchip",
        "package": "QFN40",
        "datasheet": "https://ww1.microchip.com/downloads/en/DeviceDoc/ATWILC1000-MR110xB-DS40002158B.pdf",
        "description": "IEEE 802.11 b/g/n WiFi link controller",
    },
    {
        "part": "ATECC608A",
        "aliases": ["ATECC608", "ATECC608A"],
        "category": "secure_element",
        "manufacturer": "Microchip",
        "package": "UDFN8",
        "datasheet": "https://ww1.microchip.com/downloads/en/DeviceDoc/ATECC608A-TFLXTLSS-CryptoAuthentication-DS40002007B.pdf",
        "description": "CryptoAuthentication device, ECDH/ECDSA",
    },
    # -----------------------------------------------------------------------
    # Sensors
    # -----------------------------------------------------------------------
    {
        "part": "BME280",
        "aliases": ["BME280"],
        "category": "sensor",
        "manufacturer": "Bosch",
        "package": "LGA-8",
        "datasheet": "https://www.bosch-sensortec.com/media/boschsensortec/downloads/datasheets/bst-bme280-ds002.pdf",
        "description": "Temp/humidity/pressure combo sensor, I2C/SPI",
    },
    {
        "part": "BMP280",
        "aliases": ["BMP280"],
        "category": "sensor",
        "manufacturer": "Bosch",
        "package": "LGA-8",
        "datasheet": "https://www.bosch-sensortec.com/media/boschsensortec/downloads/datasheets/bst-bmp280-ds001.pdf",
        "description": "Barometric pressure/temperature sensor, I2C/SPI",
    },
    {
        "part": "MPU-6050",
        "aliases": ["MPU6050", "MPU-6050"],
        "category": "sensor",
        "manufacturer": "TDK InvenSense",
        "package": "QFN24",
        "datasheet": "https://invensense.tdk.com/wp-content/uploads/2015/02/MPU-6000-Datasheet1.pdf",
        "description": "6-axis IMU (3-axis gyro + 3-axis accel), I2C",
    },
    {
        "part": "ADXL345",
        "aliases": ["ADXL345"],
        "category": "sensor",
        "manufacturer": "Analog Devices",
        "package": "LGA-14",
        "datasheet": "https://www.analog.com/media/en/technical-documentation/data-sheets/adxl345.pdf",
        "description": "3-axis digital accelerometer, SPI/I2C, ±16g",
    },
    {
        "part": "LIS3DH",
        "aliases": ["LIS3DH"],
        "category": "sensor",
        "manufacturer": "STMicroelectronics",
        "package": "LGA-16",
        "datasheet": "https://www.st.com/resource/en/datasheet/lis3dh.pdf",
        "description": "3-axis accelerometer, SPI/I2C, ultra-low-power",
    },
    {
        "part": "AHT20",
        "aliases": ["AHT20", "AHT10"],
        "category": "sensor",
        "manufacturer": "Aosong",
        "package": "LGA-6",
        "datasheet": "https://files.seeedstudio.com/wiki/Grove-AHT20_I2C_Industrial_Grade_Temperature_and_Humidity_Sensor/AHT20-datasheet-2020-4-16.pdf",
        "description": "Temperature/humidity sensor, I2C",
    },
    {
        "part": "SHT31-DIS",
        "aliases": ["SHT31", "SHT3X"],
        "category": "sensor",
        "manufacturer": "Sensirion",
        "package": "DFN-8",
        "datasheet": "https://sensirion.com/media/documents/213E6A3B/63A5A569/Datasheet_SHT3x_DIS.pdf",
        "description": "High-accuracy temperature/humidity, I2C",
    },
    {
        "part": "BH1750FVI",
        "aliases": ["BH1750", "BH1750FVI"],
        "category": "sensor",
        "manufacturer": "ROHM",
        "package": "SOP8",
        "datasheet": "https://www.mouser.com/datasheet/2/348/bh1750fvi-e-186247.pdf",
        "description": "Ambient light sensor, I2C, 1–65535 lux",
    },
    {
        "part": "MAX30102",
        "aliases": ["MAX30102"],
        "category": "sensor",
        "manufacturer": "Maxim",
        "package": "OLGA-14",
        "datasheet": "https://datasheets.maximintegrated.com/en/ds/MAX30102.pdf",
        "description": "Pulse oximeter/heart-rate sensor, I2C",
    },
    {
        "part": "TCS34725FN",
        "aliases": ["TCS34725", "TCS34"],
        "category": "sensor",
        "manufacturer": "ams",
        "package": "FN-16",
        "datasheet": "https://ams.com/documents/20143/36005/TCS3472_DS000390_3-00.pdf",
        "description": "RGB color sensor with IR filter, I2C",
    },
    # -----------------------------------------------------------------------
    # Audio
    # -----------------------------------------------------------------------
    {
        "part": "MAX98357AEWL",
        "aliases": ["MAX98357", "MAX98357A"],
        "category": "audio",
        "manufacturer": "Maxim",
        "package": "WLP-9",
        "datasheet": "https://datasheets.maximintegrated.com/en/ds/MAX98357A-MAX98357B.pdf",
        "description": "3.2W I2S Class D mono amplifier, no MCLK",
    },
    {
        "part": "ES8388",
        "aliases": ["ES8388"],
        "category": "audio",
        "manufacturer": "Everest Semiconductor",
        "package": "QFN28",
        "datasheet": "https://dl.espressif.com/dl/schematics/SF-AI-C1-A1-20190220.pdf",
        "description": "24-bit stereo audio CODEC, I2S/I2C",
    },
    {
        "part": "WM8960G",
        "aliases": ["WM8960", "WM8960G"],
        "category": "audio",
        "manufacturer": "Cirrus Logic",
        "package": "QFN32",
        "datasheet": "https://statics.cirrus.com/pubs/proDatasheet/WM8960_v4.2.pdf",
        "description": "Low-power stereo CODEC, mic-to-speaker",
    },
    {
        "part": "PCM5102A",
        "aliases": ["PCM5102", "PCM5102A"],
        "category": "audio",
        "manufacturer": "Texas Instruments",
        "package": "TSSOP20",
        "datasheet": "https://www.ti.com/lit/ds/symlink/pcm5102a.pdf",
        "description": "2VRMS 112dB 384kHz I2S DAC",
    },
    {
        "part": "TPA3116D2DADR",
        "aliases": ["TPA3116", "TPA3116D2"],
        "category": "audio",
        "manufacturer": "Texas Instruments",
        "package": "HTSSOP32",
        "datasheet": "https://www.ti.com/lit/ds/symlink/tpa3116d2.pdf",
        "description": "2×50W stereo Class D amplifier",
    },
    # -----------------------------------------------------------------------
    # TPM (Trusted Platform Module)
    # -----------------------------------------------------------------------
    {
        "part": "SLB9670",
        "aliases": ["SLB9670", "SLB 9670", "INFINEON SLB9670"],
        "category": "tpm",
        "manufacturer": "Infineon",
        "package": "QFN-32",
        "datasheet": "https://www.infineon.com/dgdl/Infineon-SLB9670VQ12-DataSheet-v14_10-EN.pdf",
        "description": "TPM 2.0, SPI interface, FIPS 140-2 certified",
    },
    {
        "part": "NPCT750",
        "aliases": ["NPCT750", "NPCT750A", "NUVOTON NPCT750"],
        "category": "tpm",
        "manufacturer": "Nuvoton",
        "package": "QFP-32",
        "datasheet": "https://www.nuvoton.com/resource-files/NPCT750_DS_Ver1.0.pdf",
        "description": "TPM 2.0, LPC interface",
    },
    {
        "part": "ST33TPHF2ESPI",
        "aliases": ["ST33TPHF2ESPI", "ST33TPH", "ST33"],
        "category": "tpm",
        "manufacturer": "STMicroelectronics",
        "package": "UFQFPN-32",
        "datasheet": "https://www.st.com/resource/en/datasheet/st33tphf2espi.pdf",
        "description": "TPM 2.0, SPI interface, Common Criteria EAL4+",
    },
    # -----------------------------------------------------------------------
    # Secure Elements & CryptoAuth
    # -----------------------------------------------------------------------
    {
        "part": "SE050",
        "aliases": ["SE050", "NXP SE050", "SE050C2"],
        "category": "secure_element",
        "manufacturer": "NXP",
        "package": "HX2QFN-20",
        "datasheet": "https://www.nxp.com/docs/en/data-sheet/SE050-DATASHEET.pdf",
        "description": "Secure Element, I2C, IoT security middleware, CC EAL 6+",
    },
    {
        "part": "ATECC608B",
        "aliases": ["ATECC608B", "ATECC608"],
        "category": "secure_element",
        "manufacturer": "Microchip",
        "package": "UDFN-8",
        "datasheet": "https://ww1.microchip.com/downloads/en/DeviceDoc/ATECC608B-CryptoAuthentication-Device-Summary-Data-Sheet-DS40002239B.pdf",
        "description": "CryptoAuthentication device, ECDH/ECDSA, hardware key storage (B revision)",
    },
    {
        "part": "SLS32AIA",
        "aliases": ["SLS32AIA", "SLS32", "INFINEON SLS32"],
        "category": "secure_element",
        "manufacturer": "Infineon",
        "package": "SPI",
        "datasheet": "https://www.infineon.com/cms/en/product/security-smart-card-solutions/optiga-embedded-security-solutions/optiga-trust/",
        "description": "OPTIGA Trust Anchor, SPI, mutual authentication",
    },
    {
        "part": "STSAFE-A110",
        "aliases": ["STSAFE-A110", "STSAFEA110", "STSAFE"],
        "category": "secure_element",
        "manufacturer": "STMicroelectronics",
        "package": "SO8N",
        "datasheet": "https://www.st.com/resource/en/datasheet/stsafe-a110.pdf",
        "description": "Secure Element, I2C, CC EAL5+ certified, TLS/IoT auth",
    },
    # -----------------------------------------------------------------------
    # FPGAs & CPLDs
    # -----------------------------------------------------------------------
    {
        "part": "XC7A35T",
        "aliases": ["XC7A35T", "ARTIX-7", "ARTIX7", "XC7A35"],
        "category": "fpga",
        "manufacturer": "Xilinx",
        "package": "BGA-236",
        "datasheet": "https://www.xilinx.com/support/documentation/data_sheets/ds180_7Series_Overview.pdf",
        "description": "Artix-7 FPGA, 33280 LUTs, PCIe, 6.6Gb/s transceivers",
    },
    {
        "part": "XC6SLX9",
        "aliases": ["XC6SLX9", "SPARTAN-6", "SPARTAN6", "XC6SLX9-2"],
        "category": "fpga",
        "manufacturer": "Xilinx",
        "package": "TQFP-144",
        "datasheet": "https://www.xilinx.com/support/documentation/data_sheets/ds160.pdf",
        "description": "Spartan-6 FPGA, 9152 LUTs, low-power, LPDDR support",
    },
    {
        "part": "iCE40UP5K",
        "aliases": ["ICE40UP5K", "ICE40", "ICE40UP5K-SG48"],
        "category": "fpga",
        "manufacturer": "Lattice",
        "package": "QFN-48",
        "datasheet": "https://www.latticesemi.com/view_document?document_id=51968",
        "description": "iCE40 UltraPlus FPGA, 5280 LUTs, DSP, SPRAM, open-source toolchain",
    },
    {
        "part": "10M08SAE144C8G",
        "aliases": ["MAX10", "10M08", "INTEL MAX10", "MAX10 10M08"],
        "category": "fpga",
        "manufacturer": "Intel",
        "package": "EQFP-144",
        "datasheet": "https://www.intel.com/content/www/us/en/programmable/documentation/mcn1397700832153.html",
        "description": "Intel MAX 10 FPGA, 8000 LEs, instant-on, non-volatile",
    },
    # -----------------------------------------------------------------------
    # Ethernet PHYs
    # -----------------------------------------------------------------------
    {
        "part": "88E1512",
        "aliases": ["88E1512", "MARVELL 88E1512", "88E1512-A0-NNP2C000"],
        "category": "ethernet",
        "manufacturer": "Marvell",
        "package": "QFN-56",
        "datasheet": "https://www.marvell.com/content/dam/marvell/en/public-collateral/transceivers/marvell-phys-transceivers-alaska-88e1512-datasheet.pdf",
        "description": "Gigabit Ethernet PHY, SGMII/RGMII/MDIO, copper+fiber combo",
    },
    {
        "part": "BCM5482",
        "aliases": ["BCM5482", "BROADCOM BCM5482"],
        "category": "ethernet",
        "manufacturer": "Broadcom",
        "package": "BGA-196",
        "datasheet": "https://www.broadcom.com/products/ethernet-connectivity/phy-and-poe/copper/gigabit/bcm5482",
        "description": "Dual-port Gigabit Ethernet PHY, RGMII, SerDes",
    },
    {
        "part": "RTL8211F",
        "aliases": ["RTL8211F", "RTL8211FD", "REALTEK RTL8211F"],
        "category": "ethernet",
        "manufacturer": "Realtek",
        "package": "QFN-48",
        "datasheet": "https://www.realtek.com/en/products/communications-network-ics/item/rtl8211f-i-cg",
        "description": "Gigabit Ethernet PHY, RGMII/MII/GMII, MDIO/MDC",
    },
]


def _build_lookup() -> dict[str, dict]:
    """Build a fast lookup table from all part numbers and aliases."""
    lookup: dict[str, dict] = {}
    for entry in _COMPONENT_DB:
        lookup[entry["part"].upper()] = entry
        for alias in entry.get("aliases", []):
            lookup[alias.upper()] = entry
    return lookup


_LOOKUP = _build_lookup()


def _load_learned_components(path: Path = LEARNED_DB_PATH) -> None:
    """Load persisted learned components and extend _COMPONENT_DB and _LOOKUP.

    Called once at module import time. Safe to call repeatedly — duplicate
    entries are skipped if the part key already exists in _LOOKUP.
    """
    if not path.exists():
        return
    try:
        entries: list[dict] = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return
    if not isinstance(entries, list):
        return
    for entry in entries:
        if not isinstance(entry, dict) or "part" not in entry:
            continue
        part_upper = entry["part"].upper()
        if part_upper in _LOOKUP:
            continue
        _COMPONENT_DB.append(entry)
        _LOOKUP[part_upper] = entry
        for alias in entry.get("aliases", []):
            alias_upper = alias.upper()
            if alias_upper not in _LOOKUP:
                _LOOKUP[alias_upper] = entry


def learn_component(entry: dict, path: Path = LEARNED_DB_PATH) -> None:
    """Add a new component to the runtime DB and persist it to disk.

    Args:
        entry: Dict describing the component. Must contain at least a ``part``
            key. Optional keys: ``aliases``, ``category``, ``manufacturer``,
            ``package``, ``datasheet``, ``description``.
        path: Override the persist path (useful in tests).

    Raises:
        ValueError: If *entry* is missing the required ``part`` key.
    """
    if "part" not in entry:
        raise ValueError("learn_component: entry must contain a 'part' key")

    # Update in-memory structures
    _COMPONENT_DB.append(entry)
    _LOOKUP[entry["part"].upper()] = entry
    for alias in entry.get("aliases", []):
        _LOOKUP[alias.upper()] = entry

    # Load existing persisted entries, append, save atomically
    existing: list[dict] = []
    if path.exists():
        try:
            existing = json.loads(path.read_text())
            if not isinstance(existing, list):
                existing = []
        except (json.JSONDecodeError, OSError):
            existing = []

    existing.append(entry)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(existing, indent=2))
    tmp.replace(path)


# Extend DB with any previously learned components at import time.
_load_learned_components()


def _best_fuzzy_match(marking: str, threshold: float = 0.55) -> Optional[dict]:
    """Return the best DB entry matching the marking via SequenceMatcher, or None."""
    if not marking:
        return None

    upper = marking.upper().strip()

    # Exact match first
    if upper in _LOOKUP:
        return _LOOKUP[upper]

    # Fuzzy search against all keys
    best_score = 0.0
    best_entry: Optional[dict] = None

    for key, entry in _LOOKUP.items():
        score = difflib.SequenceMatcher(None, upper, key).ratio()
        if score > best_score:
            best_score = score
            best_entry = entry

    if best_score >= threshold:
        return best_entry
    return None


def identify_components(components: list[Component]) -> list[Component]:
    """Fuzzy-match component markings against the local DB and annotate in-place.

    Each component with a non-empty marking is looked up against the component
    database. On a match the ``part_number``, ``datasheet_url``, ``package``,
    and ``value`` fields are populated.

    Args:
        components: List of Component dataclass instances (mutated in-place and
            also returned for chaining).

    Returns:
        The same list with identified fields filled in where matches were found.
    """
    for comp in components:
        if not comp.marking:
            continue
        match = _best_fuzzy_match(comp.marking)
        if match:
            comp.part_number = comp.part_number or match["part"]
            comp.datasheet_url = comp.datasheet_url or match.get("datasheet", "")
            comp.package = comp.package or match.get("package", "")
            comp.value = comp.value or match.get("description", "")
    return components


def lookup_part(marking: str) -> Optional[dict]:
    """Public single-part lookup used by tests and CLI helpers.

    Args:
        marking: Raw marking string read from the PCB.

    Returns:
        Dict with part, category, manufacturer, package, datasheet, description
        keys — or None if no match above threshold.
    """
    return _best_fuzzy_match(marking)
