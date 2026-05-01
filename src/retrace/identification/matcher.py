"""Component identification via fuzzy matching against a local component database."""

from __future__ import annotations

import difflib
import json
from pathlib import Path

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
        "security_intel": {
                "debug_interfaces": ["SWD"],
                "boot_mode_pins": ["BOOT0 (pin 44)"],
                "readout_protection": "RDP Level 0/1/2",
                "core": "Cortex-M0",
                "voltage_range": "2.4V–3.6V",
            },
        "description": "ARM Cortex-M0 48MHz, 64KB Flash",
    },
    {
        "part": "STM32F103C8T6",
        "aliases": ["STM32F103", "STM32", "103C8"],
        "category": "mcu",
        "manufacturer": "STMicroelectronics",
        "package": "LQFP48",
        "datasheet": "https://www.st.com/resource/en/datasheet/stm32f103c8.pdf",
        "security_intel": {
                "debug_interfaces": ["JTAG", "SWD"],
                "boot_mode_pins": ["BOOT0 (pin 44)", "BOOT1 (pin 20)"],
                "readout_protection": "RDP Level 0/1",
                "core": "Cortex-M3",
                "voltage_range": "2.0V–3.6V",
            },
        "description": "ARM Cortex-M3 32-bit MCU, 72MHz, 64KB Flash",
    },
    {
        "part": "STM32F205RGT6",
        "aliases": ["STM32F205", "F205RG"],
        "category": "mcu",
        "manufacturer": "STMicroelectronics",
        "package": "LQFP64",
        "datasheet": "https://www.st.com/resource/en/datasheet/stm32f205rg.pdf",
        "security_intel": {
                "debug_interfaces": ["JTAG", "SWD"],
                "boot_mode_pins": ["BOOT0 (pin 60)", "BOOT1 (pin 37)"],
                "readout_protection": "RDP Level 0/1/2",
                "core": "Cortex-M3",
                "voltage_range": "1.8V–3.6V",
            },
        "description": "ARM Cortex-M3 120MHz, 1MB Flash",
    },
    {
        "part": "STM32F303CCT6",
        "aliases": ["STM32F303", "F303CC"],
        "category": "mcu",
        "manufacturer": "STMicroelectronics",
        "package": "LQFP48",
        "datasheet": "https://www.st.com/resource/en/datasheet/stm32f303cc.pdf",
        "security_intel": {
                "debug_interfaces": ["JTAG", "SWD"],
                "boot_mode_pins": ["BOOT0 (pin 44)"],
                "readout_protection": "RDP Level 0/1/2",
                "core": "Cortex-M4F",
                "voltage_range": "2.0V–3.6V",
            },
        "description": "ARM Cortex-M4 72MHz with FPU, DSP, 256KB Flash",
    },
    {
        "part": "STM32F411CEU6",
        "aliases": ["STM32F411", "F411CEU"],
        "category": "mcu",
        "manufacturer": "STMicroelectronics",
        "package": "UFQFPN48",
        "datasheet": "https://www.st.com/resource/en/datasheet/stm32f411ce.pdf",
        "security_intel": {
                "debug_interfaces": ["JTAG", "SWD"],
                "boot_mode_pins": ["BOOT0 (pin 44)", "BOOT1 (pin 20)"],
                "readout_protection": "RDP Level 0/1/2",
                "core": "Cortex-M4F",
                "voltage_range": "1.7V–3.6V",
            },
        "description": "ARM Cortex-M4 84MHz, 512KB Flash",
    },
    {
        "part": "STM32F429ZIT6",
        "aliases": ["STM32F429", "F429ZI"],
        "category": "mcu",
        "manufacturer": "STMicroelectronics",
        "package": "LQFP144",
        "datasheet": "https://www.st.com/resource/en/datasheet/stm32f429zi.pdf",
        "security_intel": {
                "debug_interfaces": ["JTAG", "SWD"],
                "boot_mode_pins": ["BOOT0 (pin 138)", "BOOT1 (pin 37)"],
                "readout_protection": "RDP Level 0/1/2",
                "core": "Cortex-M4F",
                "voltage_range": "1.8V–3.6V",
            },
        "description": "ARM Cortex-M4 180MHz, 2MB Flash, FMC, TFT",
    },
    {
        "part": "STM32F746NGH6",
        "aliases": ["STM32F746", "F746NG"],
        "category": "mcu",
        "manufacturer": "STMicroelectronics",
        "package": "TFBGA216",
        "datasheet": "https://www.st.com/resource/en/datasheet/stm32f746ng.pdf",
        "security_intel": {
                "debug_interfaces": ["JTAG", "SWD"],
                "boot_mode_pins": ["BOOT0 (pin A7)"],
                "readout_protection": "RDP Level 0/1/2",
                "core": "Cortex-M7",
                "voltage_range": "1.7V–3.6V",
            },
        "description": "ARM Cortex-M7 216MHz, 1MB Flash",
    },
    {
        "part": "STM32H743ZIT6",
        "aliases": ["STM32H743", "H743ZI"],
        "category": "mcu",
        "manufacturer": "STMicroelectronics",
        "package": "LQFP144",
        "datasheet": "https://www.st.com/resource/en/datasheet/stm32h743zi.pdf",
        "security_intel": {
                "debug_interfaces": ["JTAG", "SWD"],
                "boot_mode_pins": ["BOOT0 (pin 138)"],
                "readout_protection": "RDP Level 0/0.5/1/2",
                "core": "Cortex-M7",
                "voltage_range": "1.62V–3.6V",
            },
        "description": "ARM Cortex-M7 480MHz, 2MB Flash, DP-FPU",
    },
    {
        "part": "STM32L010C6T6",
        "aliases": ["STM32L010", "L010C6"],
        "category": "mcu",
        "manufacturer": "STMicroelectronics",
        "package": "LQFP48",
        "datasheet": "https://www.st.com/resource/en/datasheet/stm32l010c6.pdf",
        "security_intel": {
                "debug_interfaces": ["SWD"],
                "boot_mode_pins": ["BOOT0 (pin 44)"],
                "readout_protection": "RDP Level 0/1/2",
                "core": "Cortex-M0+",
                "voltage_range": "1.8V–3.6V",
            },
        "description": "ARM Cortex-M0+ ultra-low-power, 32KB Flash",
    },
    {
        "part": "STM32L151CBT6",
        "aliases": ["STM32L151", "L151CB"],
        "category": "mcu",
        "manufacturer": "STMicroelectronics",
        "package": "LQFP48",
        "datasheet": "https://www.st.com/resource/en/datasheet/stm32l151cb.pdf",
        "security_intel": {
                "debug_interfaces": ["JTAG", "SWD"],
                "boot_mode_pins": ["BOOT0 (pin 44)"],
                "readout_protection": "RDP Level 0/1/2",
                "core": "Cortex-M3",
                "voltage_range": "1.8V–3.6V",
            },
        "description": "ARM Cortex-M3 ultra-low-power 32MHz, 128KB Flash",
    },
    {
        "part": "STM32L476RGT6",
        "aliases": ["STM32L476", "L476RG"],
        "category": "mcu",
        "manufacturer": "STMicroelectronics",
        "package": "LQFP64",
        "datasheet": "https://www.st.com/resource/en/datasheet/stm32l476rg.pdf",
        "security_intel": {
                "debug_interfaces": ["JTAG", "SWD"],
                "boot_mode_pins": ["BOOT0 (pin 60)"],
                "readout_protection": "RDP Level 0/1/2",
                "core": "Cortex-M4F",
                "voltage_range": "1.71V–3.6V",
            },
        "description": "ARM Cortex-M4 80MHz ultra-low-power, 1MB Flash",
    },
    {
        "part": "STM32G031K8T6",
        "aliases": ["STM32G031", "G031K8"],
        "category": "mcu",
        "manufacturer": "STMicroelectronics",
        "package": "LQFP32",
        "datasheet": "https://www.st.com/resource/en/datasheet/stm32g031k8.pdf",
        "security_intel": {
                "debug_interfaces": ["SWD"],
                "boot_mode_pins": ["BOOT0 (pin 31)"],
                "readout_protection": "RDP Level 0/1/2",
                "core": "Cortex-M0+",
                "voltage_range": "2.0V–3.6V",
            },
        "description": "ARM Cortex-M0+ 64MHz, 64KB Flash",
    },
    {
        "part": "STM32G474RET6",
        "aliases": ["STM32G474", "G474RE"],
        "category": "mcu",
        "manufacturer": "STMicroelectronics",
        "package": "LQFP64",
        "datasheet": "https://www.st.com/resource/en/datasheet/stm32g474re.pdf",
        "security_intel": {
                "debug_interfaces": ["JTAG", "SWD"],
                "boot_mode_pins": ["BOOT0 (pin 60)"],
                "readout_protection": "RDP Level 0/1/2",
                "core": "Cortex-M4F",
                "voltage_range": "1.71V–3.6V",
            },
        "description": "ARM Cortex-M4 170MHz, HRTIM, 512KB Flash",
    },
    {
        "part": "STM32U575CIT6",
        "aliases": ["STM32U575", "U575CI"],
        "category": "mcu",
        "manufacturer": "STMicroelectronics",
        "package": "LQFP48",
        "datasheet": "https://www.st.com/resource/en/datasheet/stm32u575ci.pdf",
        "security_intel": {
                "debug_interfaces": ["JTAG", "SWD"],
                "boot_mode_pins": ["BOOT0 (pin 44)"],
                "readout_protection": "RDP Level 0/0.5/1/2",
                "core": "Cortex-M33",
                "voltage_range": "1.71V–3.6V",
            },
        "description": "ARM Cortex-M33 160MHz ultra-low-power, 2MB Flash",
    },
    {
        "part": "STM32WB55RGV6",
        "aliases": ["STM32WB55", "WB55RG"],
        "category": "mcu",
        "manufacturer": "STMicroelectronics",
        "package": "VFQFPN68",
        "datasheet": "https://www.st.com/resource/en/datasheet/stm32wb55rg.pdf",
        "security_intel": {
                "debug_interfaces": ["JTAG", "SWD"],
                "boot_mode_pins": ["BOOT0 (pin 51)"],
                "readout_protection": "RDP Level 0/1/2",
                "core": "Cortex-M4F + M0+",
                "voltage_range": "1.71V–3.6V",
            },
        "description": "ARM Cortex-M4 + M0+ BLE/802.15.4 SoC, 1MB Flash",
    },
    {
        "part": "STM32WL55JCI6",
        "aliases": ["STM32WL55", "WL55JC"],
        "category": "mcu",
        "manufacturer": "STMicroelectronics",
        "package": "UFBGA73",
        "datasheet": "https://www.st.com/resource/en/datasheet/stm32wl55jc.pdf",
        "security_intel": {
                "debug_interfaces": ["JTAG", "SWD"],
                "boot_mode_pins": ["BOOT0"],
                "readout_protection": "RDP Level 0/1/2",
                "core": "Cortex-M4 + M0+",
                "voltage_range": "1.8V–3.6V",
            },
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
        "security_intel": {
                "debug_interfaces": ["JTAG"],
                "boot_mode_pins": ["GPIO0 (strapping)", "GPIO2 (strapping)"],
                "readout_protection": "Flash Encryption + Secure Boot (eFuse)",
                "core": "Xtensa LX6 dual-core",
                "voltage_range": "2.2V–3.6V",
            },
        "description": "Dual-core Xtensa 240MHz, WiFi+BT, 4MB Flash",
    },
    {
        "part": "ESP32-S2",
        "aliases": ["ESP32S2", "ESP32-S2-WROOM"],
        "category": "mcu",
        "manufacturer": "Espressif",
        "package": "Module",
        "datasheet": "https://www.espressif.com/sites/default/files/documentation/esp32-s2_datasheet_en.pdf",
        "security_intel": {
                "debug_interfaces": ["JTAG", "USB-JTAG"],
                "boot_mode_pins": ["GPIO0 (strapping)", "GPIO46 (strapping)"],
                "readout_protection": "Flash Encryption + Secure Boot V2 (eFuse)",
                "core": "Xtensa LX7",
                "voltage_range": "2.2V–3.6V",
            },
        "description": "Xtensa LX7 240MHz, WiFi, USB OTG, 4MB Flash",
    },
    {
        "part": "ESP32-S3",
        "aliases": ["ESP32S3", "ESP32-S3-WROOM"],
        "category": "mcu",
        "manufacturer": "Espressif",
        "package": "Module",
        "datasheet": "https://www.espressif.com/sites/default/files/documentation/esp32-s3_datasheet_en.pdf",
        "security_intel": {
                "debug_interfaces": ["JTAG", "USB-JTAG"],
                "boot_mode_pins": ["GPIO0 (strapping)", "GPIO46 (strapping)"],
                "readout_protection": "Flash Encryption + Secure Boot V2 (eFuse)",
                "core": "Xtensa LX7 dual-core",
                "voltage_range": "2.2V–3.6V",
            },
        "description": "Dual-core Xtensa LX7 240MHz, WiFi+BT5, AI accelerator",
    },
    {
        "part": "ESP32-C3",
        "aliases": ["ESP32C3", "ESP32-C3-MINI"],
        "category": "mcu",
        "manufacturer": "Espressif",
        "package": "Module",
        "datasheet": "https://www.espressif.com/sites/default/files/documentation/esp32-c3_datasheet_en.pdf",
        "security_intel": {
                "debug_interfaces": ["JTAG", "USB-JTAG"],
                "boot_mode_pins": ["GPIO2 (strapping)", "GPIO8 (strapping)", "GPIO9 (strapping)"],
                "readout_protection": "Flash Encryption + Secure Boot V2 (eFuse)",
                "core": "RISC-V",
                "voltage_range": "2.2V–3.6V",
            },
        "description": "RISC-V 160MHz, WiFi+BT5, 4MB Flash",
    },
    {
        "part": "ESP32-C6",
        "aliases": ["ESP32C6", "ESP32-C6-MINI"],
        "category": "mcu",
        "manufacturer": "Espressif",
        "package": "Module",
        "datasheet": "https://www.espressif.com/sites/default/files/documentation/esp32-c6_datasheet_en.pdf",
        "security_intel": {
                "debug_interfaces": ["JTAG", "USB-JTAG"],
                "boot_mode_pins": ["GPIO9 (strapping)"],
                "readout_protection": "Flash Encryption + Secure Boot V2 (eFuse)",
                "core": "RISC-V",
                "voltage_range": "2.2V–3.6V",
            },
        "description": "RISC-V 160MHz, WiFi6+BT5+802.15.4, 4MB Flash",
    },
    {
        "part": "ESP32-H2",
        "aliases": ["ESP32H2"],
        "category": "mcu",
        "manufacturer": "Espressif",
        "package": "Module",
        "datasheet": "https://www.espressif.com/sites/default/files/documentation/esp32-h2_datasheet_en.pdf",
        "security_intel": {
                "debug_interfaces": ["JTAG", "USB-JTAG"],
                "boot_mode_pins": ["GPIO9 (strapping)"],
                "readout_protection": "Flash Encryption + Secure Boot V2 (eFuse)",
                "core": "RISC-V",
                "voltage_range": "2.2V–3.6V",
            },
        "description": "RISC-V 96MHz, BT5+802.15.4 (Zigbee/Thread), no WiFi",
    },
    {
        "part": "ESP8266EX",
        "aliases": ["ESP8266", "ESP-12", "ESP-07"],
        "category": "mcu",
        "manufacturer": "Espressif",
        "package": "QFN32",
        "datasheet": "https://www.espressif.com/sites/default/files/documentation/0a-esp8266ex_datasheet_en.pdf",
        "security_intel": {
                "debug_interfaces": ["JTAG"],
                "boot_mode_pins": ["GPIO0", "GPIO2", "GPIO15"],
                "readout_protection": "None (external flash only)",
                "core": "Xtensa L106",
                "voltage_range": "2.5V–3.6V",
            },
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
        "security_intel": {
                "debug_interfaces": ["debugWIRE", "ISP"],
                "boot_mode_pins": ["RESET (pin 1)"],
                "readout_protection": "Lock bits (LB1/LB2)",
                "core": "AVR 8-bit",
                "voltage_range": "1.8V–5.5V",
            },
        "description": "8-bit AVR, 20MHz, 32KB Flash",
    },
    {
        "part": "ATmega2560",
        "aliases": ["ATMEGA2560", "2560"],
        "category": "mcu",
        "manufacturer": "Microchip",
        "package": "TQFP100",
        "datasheet": "https://ww1.microchip.com/downloads/en/DeviceDoc/ATmega640-1280-1281-2560-2561-Datasheet-DS40002211A.pdf",
        "security_intel": {
                "debug_interfaces": ["JTAG", "ISP"],
                "boot_mode_pins": ["RESET (pin 1)"],
                "readout_protection": "Lock bits (LB1/LB2)",
                "core": "AVR 8-bit",
                "voltage_range": "4.5V–5.5V",
            },
        "description": "8-bit AVR, 16MHz, 256KB Flash",
    },
    {
        "part": "ATmega32U4",
        "aliases": ["ATMEGA32U4", "32U4"],
        "category": "mcu",
        "manufacturer": "Microchip",
        "package": "TQFP44",
        "datasheet": "https://ww1.microchip.com/downloads/en/DeviceDoc/Atmel-7766-8-bit-AVR-ATmega16U4-32U4_Datasheet.pdf",
        "security_intel": {
                "debug_interfaces": ["JTAG", "ISP"],
                "boot_mode_pins": ["RESET (pin 13)", "HWB (pin 33)"],
                "readout_protection": "Lock bits (LB1/LB2)",
                "core": "AVR 8-bit",
                "voltage_range": "2.7V–5.5V",
            },
        "description": "8-bit AVR with native USB, 16MHz, 32KB Flash",
    },
    {
        "part": "ATtiny85",
        "aliases": ["ATTINY85", "TINY85"],
        "category": "mcu",
        "manufacturer": "Microchip",
        "package": "SOIC8",
        "datasheet": "https://ww1.microchip.com/downloads/en/DeviceDoc/Atmel-2586-AVR-8-bit-Microcontroller-ATtiny25-ATtiny45-ATtiny85_Datasheet.pdf",
        "security_intel": {
                "debug_interfaces": ["debugWIRE", "ISP"],
                "boot_mode_pins": ["RESET (pin 1)"],
                "readout_protection": "Lock bits",
                "core": "AVR 8-bit",
                "voltage_range": "2.7V–5.5V",
            },
        "description": "8-bit AVR, 20MHz, 8KB Flash, 8-pin",
    },
    {
        "part": "ATtiny84",
        "aliases": ["ATTINY84", "TINY84"],
        "category": "mcu",
        "manufacturer": "Microchip",
        "package": "SOIC14",
        "datasheet": "https://ww1.microchip.com/downloads/en/DeviceDoc/ATtiny24A-44A-84A-DataSheet-DS40002269A.pdf",
        "security_intel": {
                "debug_interfaces": ["debugWIRE", "ISP"],
                "boot_mode_pins": ["RESET (pin 4)"],
                "readout_protection": "Lock bits",
                "core": "AVR 8-bit",
                "voltage_range": "2.7V–5.5V",
            },
        "description": "8-bit AVR, 20MHz, 8KB Flash, 14-pin",
    },
    {
        "part": "ATtiny13",
        "aliases": ["ATTINY13", "TINY13"],
        "category": "mcu",
        "manufacturer": "Microchip",
        "package": "SOIC8",
        "datasheet": "https://ww1.microchip.com/downloads/en/DeviceDoc/Atmel-2535-AVR-ATtiny13_Datasheet.pdf",
        "security_intel": {
                "debug_interfaces": ["debugWIRE", "ISP"],
                "boot_mode_pins": ["RESET (pin 1)"],
                "readout_protection": "Lock bits",
                "core": "AVR 8-bit",
                "voltage_range": "2.7V–5.5V",
            },
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
        "security_intel": {
                "debug_interfaces": ["ICSP"],
                "boot_mode_pins": ["MCLR (pin 1)"],
                "readout_protection": "Code Protect (CP) fuse bits",
                "core": "PIC 8-bit",
                "voltage_range": "2.0V–5.5V",
            },
        "description": "8-bit PIC, 20MHz, 14KB Flash",
    },
    {
        "part": "PIC18F4550",
        "aliases": ["PIC18F4550", "18F4550"],
        "category": "mcu",
        "manufacturer": "Microchip",
        "package": "PDIP40",
        "datasheet": "https://ww1.microchip.com/downloads/en/DeviceDoc/39632e.pdf",
        "security_intel": {
                "debug_interfaces": ["ICSP", "ICD"],
                "boot_mode_pins": ["MCLR (pin 1)"],
                "readout_protection": "Code Protect (CP) + Write Protect (WP) fuse bits",
                "core": "PIC 8-bit",
                "voltage_range": "2.0V–5.5V",
            },
        "description": "8-bit PIC with USB, 48MHz, 32KB Flash",
    },
    {
        "part": "PIC24FJ128GA010",
        "aliases": ["PIC24FJ", "24FJ128"],
        "category": "mcu",
        "manufacturer": "Microchip",
        "package": "TQFP100",
        "datasheet": "https://ww1.microchip.com/downloads/en/DeviceDoc/39747b.pdf",
        "security_intel": {
                "debug_interfaces": ["ICSP", "ICD"],
                "boot_mode_pins": ["MCLR (pin 7)"],
                "readout_protection": "Code Guard Security (GS) fuse bits",
                "core": "PIC 16-bit",
                "voltage_range": "2.0V–3.6V",
            },
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
        "security_intel": {
                "debug_interfaces": ["SWD"],
                "boot_mode_pins": ["QSPI_SS (pin 27) hold low for USB boot"],
                "readout_protection": "None (no secure boot in hardware)",
                "core": "Cortex-M0+ dual-core",
                "voltage_range": "1.8V–3.3V",
            },
        "description": "Dual Cortex-M0+, 133MHz, 264KB SRAM",
    },
    {
        "part": "nRF52832",
        "aliases": ["NRF52832", "NRF52"],
        "category": "mcu",
        "manufacturer": "Nordic Semiconductor",
        "package": "QFN48",
        "datasheet": "https://infocenter.nordicsemi.com/pdf/nRF52832_PS_v1.4.pdf",
        "security_intel": {
                "debug_interfaces": ["JTAG", "SWD"],
                "boot_mode_pins": ["RESET (pin P0.21)"],
                "readout_protection": "APPROTECT (access port protection)",
                "core": "Cortex-M4F",
                "voltage_range": "1.7V–3.6V",
            },
        "description": "ARM Cortex-M4 64MHz, BLE5, 512KB Flash",
    },
    {
        "part": "nRF52840",
        "aliases": ["NRF52840"],
        "category": "mcu",
        "manufacturer": "Nordic Semiconductor",
        "package": "AQFN73",
        "datasheet": "https://infocenter.nordicsemi.com/pdf/nRF52840_PS_v1.1.pdf",
        "security_intel": {
                "debug_interfaces": ["JTAG", "SWD"],
                "boot_mode_pins": ["RESET (pin P0.18)"],
                "readout_protection": "APPROTECT + Secure APPROTECT",
                "core": "Cortex-M4F",
                "voltage_range": "1.7V–5.5V",
            },
        "description": "ARM Cortex-M4 64MHz, BLE5+USB+802.15.4, 1MB Flash",
    },
    {
        "part": "nRF5340",
        "aliases": ["NRF5340"],
        "category": "mcu",
        "manufacturer": "Nordic Semiconductor",
        "package": "AQFN94",
        "datasheet": "https://infocenter.nordicsemi.com/pdf/nRF5340_PS_v1.3.pdf",
        "security_intel": {
                "debug_interfaces": ["JTAG", "SWD"],
                "boot_mode_pins": ["RESET"],
                "readout_protection": "APPROTECT + SECUREAPPROTECT + TrustZone",
                "core": "Cortex-M33 + Cortex-M33",
                "voltage_range": "1.7V–5.5V",
            },
        "description": "Dual-core Cortex-M33, BLE5.3+802.15.4, 1MB Flash",
    },
    {
        "part": "CC2652R",
        "aliases": ["CC2652", "CC2652R"],
        "category": "mcu",
        "manufacturer": "Texas Instruments",
        "package": "VQFN48",
        "datasheet": "https://www.ti.com/lit/ds/symlink/cc2652r.pdf",
        "security_intel": {
                "debug_interfaces": ["JTAG", "SWD", "cJTAG"],
                "boot_mode_pins": ["DIO_13 (bootloader entry)", "DIO_14 (bootloader entry)"],
                "readout_protection": "CCFG:BL_CONFIG disable + DAP lock",
                "core": "Cortex-M4F",
                "voltage_range": "1.8V–3.8V",
            },
        "description": "ARM Cortex-M4 48MHz, multi-protocol (BLE/Zigbee/Thread)",
    },
    {
        "part": "MSP430G2553",
        "aliases": ["MSP430", "MSP430G2", "G2553"],
        "category": "mcu",
        "manufacturer": "Texas Instruments",
        "package": "PDIP20",
        "datasheet": "https://www.ti.com/lit/ds/symlink/msp430g2553.pdf",
        "security_intel": {
                "debug_interfaces": ["Spy-Bi-Wire", "JTAG"],
                "boot_mode_pins": ["RST/NMI (pin 16)", "TEST (pin 17)"],
                "readout_protection": "JTAG fuse blow (one-time)",
                "core": "MSP430 16-bit",
                "voltage_range": "1.8V–3.6V",
            },
        "description": "16-bit ultra-low-power, 16MHz, 16KB Flash",
    },
    {
        "part": "ATSAMD21G18A",
        "aliases": ["SAMD21", "SAM D21", "SAMD21G18"],
        "category": "mcu",
        "manufacturer": "Microchip",
        "package": "TQFP48",
        "datasheet": "https://ww1.microchip.com/downloads/en/DeviceDoc/SAM-D21DA1-Family-Data-Sheet-DS40001882G.pdf",
        "security_intel": {
                "debug_interfaces": ["SWD"],
                "boot_mode_pins": ["RESET (pin 26)"],
                "readout_protection": "Security bit (one-time, chip erase to clear)",
                "core": "Cortex-M0+",
                "voltage_range": "1.62V–3.63V",
            },
        "description": "ARM Cortex-M0+ 48MHz, 256KB Flash, USB",
    },
    {
        "part": "ATSAME70Q21B",
        "aliases": ["SAME70", "SAM E70"],
        "category": "mcu",
        "manufacturer": "Microchip",
        "package": "LQFP144",
        "datasheet": "https://ww1.microchip.com/downloads/en/DeviceDoc/SAM-E70-S70-V70-V71-Family-Data-Sheet-DS60001527E.pdf",
        "security_intel": {
                "debug_interfaces": ["JTAG", "SWD"],
                "boot_mode_pins": ["ERASE (pin 138)", "TST (pin 136)"],
                "readout_protection": "Security bit + GPNVM bits",
                "core": "Cortex-M7",
                "voltage_range": "1.7V–3.6V",
            },
        "description": "ARM Cortex-M7 300MHz, 2MB Flash, EtherMAC",
    },
    {
        "part": "GD32F103CBT6",
        "aliases": ["GD32F103", "GD32"],
        "category": "mcu",
        "manufacturer": "GigaDevice",
        "package": "LQFP48",
        "datasheet": "https://www.gigadevice.com/datasheet/gd32f103xx-datasheet/",
        "security_intel": {
                "debug_interfaces": ["JTAG", "SWD"],
                "boot_mode_pins": ["BOOT0 (pin 44)", "BOOT1 (pin 20)"],
                "readout_protection": "SPC (Security Protection Code) Level 0/1/2",
                "core": "Cortex-M3",
                "voltage_range": "2.6V–3.6V",
            },
        "description": "ARM Cortex-M3 108MHz, 128KB Flash (STM32 clone)",
    },
    {
        "part": "CC2540",
        "aliases": ["CC2540", "CC2540F256"],
        "category": "mcu",
        "manufacturer": "Texas Instruments",
        "package": "QFN40",
        "datasheet": "https://www.ti.com/lit/ds/symlink/cc2540.pdf",
        "security_intel": {
                "debug_interfaces": ["Debug (CC Debugger)"],
                "boot_mode_pins": ["P2_1 (DC pin)", "P2_2 (DD pin)"],
                "readout_protection": "Debug lock via DBGDATA",
                "core": "8051",
                "voltage_range": "2.0V–3.6V",
            },
        "description": "8051 BLE SoC, 32MHz, 256KB Flash",
    },
    {
        "part": "CC2530",
        "aliases": ["CC2530", "CC2530F256"],
        "category": "rf",
        "manufacturer": "Texas Instruments",
        "package": "QFN40",
        "datasheet": "https://www.ti.com/lit/ds/symlink/cc2530.pdf",
        "security_intel": {
                "interface": "SPI/UART",
                "frequency": "2.4GHz",
                "protocol": "ZigBee / IEEE 802.15.4",
                "debug_relevance": "ZigBee coordinator/router — sniffable with KillerBee/Wireshark",
            },
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
        "security_intel": {
                "output_voltage": "5.0V fixed",
                "enable_pin": "None (always on)",
                "input_range": "7V–25V",
                "current_max": "1A",
            },
        "description": "1A linear regulator, 5V fixed output",
    },
    {
        "part": "LM7812",
        "aliases": ["7812", "L7812"],
        "category": "regulator",
        "manufacturer": "Texas Instruments",
        "package": "TO-220",
        "datasheet": "https://www.ti.com/lit/ds/symlink/lm7812.pdf",
        "security_intel": {
                "output_voltage": "12V fixed",
                "enable_pin": "None (always on)",
                "input_range": "14.5V–27V",
                "current_max": "1A",
            },
        "description": "1A linear regulator, 12V fixed output",
    },
    {
        "part": "L7833",
        "aliases": ["7833", "L7833CV", "L7833ABV"],
        "category": "regulator",
        "manufacturer": "STMicroelectronics",
        "package": "TO-220",
        "datasheet": "https://www.st.com/resource/en/datasheet/l78.pdf",
        "security_intel": {
                "output_voltage": "3.3V fixed",
                "enable_pin": "None (always on)",
                "input_range": "5V–20V",
                "current_max": "1A",
            },
        "description": "1A linear regulator, 3.3V fixed output",
    },
    {
        "part": "LM317T",
        "aliases": ["LM317", "LM317L"],
        "category": "regulator",
        "manufacturer": "Texas Instruments",
        "package": "TO-220",
        "datasheet": "https://www.ti.com/lit/ds/symlink/lm317.pdf",
        "security_intel": {
                "output_voltage": "1.25V–37V adjustable",
                "enable_pin": "None (always on)",
                "input_range": "3V–40V",
                "current_max": "1.5A",
            },
        "description": "1.5A adjustable LDO, 1.25V–37V",
    },
    {
        "part": "LM1117-3.3",
        "aliases": ["LM1117", "LM1117T", "LD1117"],
        "category": "regulator",
        "manufacturer": "Texas Instruments",
        "package": "SOT-223",
        "datasheet": "https://www.ti.com/lit/ds/symlink/lm1117.pdf",
        "security_intel": {
                "output_voltage": "3.3V fixed",
                "enable_pin": "None (always on)",
                "input_range": "4.75V–10V",
                "current_max": "800mA",
            },
        "description": "800mA LDO, 3.3V output",
    },
    {
        "part": "LM1117-5.0",
        "aliases": ["LM1117-5", "LD1117-5"],
        "category": "regulator",
        "manufacturer": "Texas Instruments",
        "package": "SOT-223",
        "datasheet": "https://www.ti.com/lit/ds/symlink/lm1117.pdf",
        "security_intel": {
                "output_voltage": "5.0V fixed",
                "enable_pin": "None (always on)",
                "input_range": "6.5V–15V",
                "current_max": "800mA",
            },
        "description": "800mA LDO, 5.0V output",
    },
    {
        "part": "AMS1117-3.3",
        "aliases": ["AMS1117", "AMS1117-3.3", "AMS117"],
        "category": "regulator",
        "manufacturer": "Advanced Monolithic Systems",
        "package": "SOT-223",
        "datasheet": "http://www.advanced-monolithic.com/pdf/ds1117.pdf",
        "security_intel": {
                "output_voltage": "3.3V fixed",
                "enable_pin": "None (always on)",
                "input_range": "4.5V–12V",
                "current_max": "1A",
            },
        "description": "1A LDO, adjustable/fixed 1.5V–5V",
    },
    {
        "part": "AMS1117-1.8",
        "aliases": ["AMS1117-1.8", "AMS117-1.8"],
        "category": "regulator",
        "manufacturer": "Advanced Monolithic Systems",
        "package": "SOT-223",
        "datasheet": "http://www.advanced-monolithic.com/pdf/ds1117.pdf",
        "security_intel": {
                "output_voltage": "1.8V fixed",
                "enable_pin": "None (always on)",
                "input_range": "3V–12V",
                "current_max": "1A",
            },
        "description": "1A LDO, 1.8V fixed output",
    },
    {
        "part": "AP2112K-3.3",
        "aliases": ["AP2112", "AP2112K"],
        "category": "regulator",
        "manufacturer": "Diodes Inc",
        "package": "SOT-25",
        "datasheet": "https://www.diodes.com/assets/Datasheets/AP2112.pdf",
        "security_intel": {
                "output_voltage": "3.3V fixed",
                "enable_pin": "EN (pin 3, active high)",
                "input_range": "2.5V–6V",
                "current_max": "600mA",
            },
        "description": "600mA LDO, 3.3V, CMOS low dropout",
    },
    {
        "part": "TPS7A3301DGNR",
        "aliases": ["TPS7A33", "TPS7A3301"],
        "category": "regulator",
        "manufacturer": "Texas Instruments",
        "package": "MSOP-8",
        "datasheet": "https://www.ti.com/lit/ds/symlink/tps7a33.pdf",
        "security_intel": {
                "output_voltage": "Adjustable (set by resistor divider)",
                "enable_pin": "EN (pin 5, active high)",
                "input_range": "1.4V–6.5V",
                "current_max": "100mA",
            },
        "description": "100mA ultra-low-noise LDO, adjustable",
    },
    {
        "part": "MCP1700T-3302E",
        "aliases": ["MCP1700", "MCP1700T"],
        "category": "regulator",
        "manufacturer": "Microchip",
        "package": "SOT-23",
        "datasheet": "https://ww1.microchip.com/downloads/en/DeviceDoc/20001826D.pdf",
        "security_intel": {
                "output_voltage": "3.3V fixed",
                "enable_pin": "None (always on)",
                "input_range": "2.3V–6V",
                "current_max": "250mA",
            },
        "description": "250mA low quiescent LDO, 3.3V",
    },
    {
        "part": "NCV8114ASN330T1G",
        "aliases": ["NCV8114", "NCV8114A"],
        "category": "regulator",
        "manufacturer": "onsemi",
        "package": "SOT-23-5",
        "datasheet": "https://www.onsemi.com/pdf/datasheet/ncv8114a-d.pdf",
        "security_intel": {
                "output_voltage": "3.3V fixed",
                "enable_pin": "EN (pin 3, active high)",
                "input_range": "2.5V–5.5V",
                "current_max": "150mA",
            },
        "description": "150mA LDO, 3.3V, low noise",
    },
    {
        "part": "RT9013-33GB",
        "aliases": ["RT9013", "RT9013-33"],
        "category": "regulator",
        "manufacturer": "Richtek",
        "package": "SOT-23-5",
        "datasheet": "https://www.richtek.com/assets/product_file/RT9013/DS9013-08.pdf",
        "security_intel": {
                "output_voltage": "3.3V fixed",
                "enable_pin": "EN (pin 3, active high)",
                "input_range": "2.5V–5.5V",
                "current_max": "500mA",
            },
        "description": "500mA LDO, 3.3V, low noise",
    },
    {
        "part": "SPX3819M5-L-3-3",
        "aliases": ["SPX3819", "SPX3819M5"],
        "category": "regulator",
        "manufacturer": "MaxLinear",
        "package": "SOT-23-5",
        "datasheet": "https://www.maxlinear.com/ds/spx3819.pdf",
        "security_intel": {
                "output_voltage": "3.3V fixed",
                "enable_pin": "EN (pin 3, active high)",
                "input_range": "2.5V–6V",
                "current_max": "500mA",
            },
        "description": "500mA LDO, 3.3V fixed",
    },
    {
        "part": "TLV1117-33IDCYR",
        "aliases": ["TLV1117", "TLV1117-33"],
        "category": "regulator",
        "manufacturer": "Texas Instruments",
        "package": "SOT-223",
        "datasheet": "https://www.ti.com/lit/ds/symlink/tlv1117.pdf",
        "security_intel": {
                "output_voltage": "3.3V fixed",
                "enable_pin": "None (always on)",
                "input_range": "4.75V–10V",
                "current_max": "800mA",
            },
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
        "security_intel": {
                "output_voltage": "0.6V–Vin adjustable",
                "enable_pin": "EN (pin 7, active high)",
                "input_range": "4.5V–24V",
                "current_max": "3A",
                "topology": "Synchronous Buck",
            },
        "description": "3A high-efficiency buck converter",
    },
    {
        "part": "TPS62160DSGR",
        "aliases": ["TPS62160", "TPS6216"],
        "category": "power",
        "manufacturer": "Texas Instruments",
        "package": "WSON-8",
        "datasheet": "https://www.ti.com/lit/ds/symlink/tps62160.pdf",
        "security_intel": {
                "output_voltage": "Adjustable (0.9V–6V)",
                "enable_pin": "EN (pin 6)",
                "input_range": "3V–17V",
                "current_max": "1A",
                "topology": "Buck",
            },
        "description": "1A step-down converter, 3–17V input",
    },
    {
        "part": "TPS63020DSJR",
        "aliases": ["TPS63020"],
        "category": "power",
        "manufacturer": "Texas Instruments",
        "package": "VSON-10",
        "datasheet": "https://www.ti.com/lit/ds/symlink/tps63020.pdf",
        "security_intel": {
                "output_voltage": "Adjustable (1.2V–5.5V)",
                "enable_pin": "EN (pin 11)",
                "input_range": "1.8V–5.5V",
                "current_max": "2A",
                "topology": "Buck-Boost",
            },
        "description": "2A buck-boost converter, Li-ion range",
    },
    {
        "part": "LTC3780EG",
        "aliases": ["LTC3780"],
        "category": "power",
        "manufacturer": "Analog Devices",
        "package": "SSOP28",
        "datasheet": "https://www.analog.com/media/en/technical-documentation/data-sheets/3780fb.pdf",
        "security_intel": {
                "output_voltage": "0.8V–30V adjustable",
                "enable_pin": "RUN (pin 13)",
                "input_range": "4V–36V",
                "current_max": "10A",
                "topology": "Synchronous Buck-Boost",
            },
        "description": "High-efficiency synchronous buck-boost, 4–30V",
    },
    {
        "part": "MP1584EN",
        "aliases": ["MP1584", "MP1584EN"],
        "category": "power",
        "manufacturer": "Monolithic Power Systems",
        "package": "SOIC8",
        "datasheet": "https://www.monolithicpower.com/pub/media/document/MP1584_r1.0.pdf",
        "security_intel": {
                "output_voltage": "0.8V–25V adjustable",
                "enable_pin": "EN (pin 7, active high)",
                "input_range": "4.5V–28V",
                "current_max": "3A",
                "topology": "Buck",
            },
        "description": "3A buck converter, 4.5–28V input",
    },
    {
        "part": "MP2307DN",
        "aliases": ["MP2307"],
        "category": "power",
        "manufacturer": "Monolithic Power Systems",
        "package": "SOIC8",
        "datasheet": "https://www.monolithicpower.com/pub/media/document/MP2307_r1.9.pdf",
        "security_intel": {
                "output_voltage": "0.925V–20V adjustable",
                "enable_pin": "EN (pin 5)",
                "input_range": "4.75V–23V",
                "current_max": "3A",
                "topology": "Synchronous Buck",
            },
        "description": "3A 23V synchronous rectified step-down",
    },
    {
        "part": "RT8059GJ5",
        "aliases": ["RT8059"],
        "category": "power",
        "manufacturer": "Richtek",
        "package": "SOT-23-5",
        "datasheet": "https://www.richtek.com/assets/product_file/RT8059/DS8059-02.pdf",
        "security_intel": {
                "output_voltage": "0.6V–Vin adjustable",
                "enable_pin": "EN (pin 3)",
                "input_range": "2.3V–5.5V",
                "current_max": "1.5A",
                "topology": "PWM Buck",
            },
        "description": "1.5A PWM buck converter, 0.6V–Vin output",
    },
    {
        "part": "SY8089AAAC",
        "aliases": ["SY8089"],
        "category": "power",
        "manufacturer": "Silergy",
        "package": "SOT-23-5",
        "datasheet": "https://www.silergy.com/download/SY8089A.pdf",
        "security_intel": {
                "output_voltage": "0.6V–Vin adjustable",
                "enable_pin": "EN (pin 3)",
                "input_range": "2.5V–5.5V",
                "current_max": "2A",
                "topology": "Synchronous Buck",
            },
        "description": "2A synchronous buck converter, 1MHz",
    },
    {
        "part": "AP3418KTR-G1",
        "aliases": ["AP3418"],
        "category": "power",
        "manufacturer": "Diodes Inc",
        "package": "SOT-23-6",
        "datasheet": "https://www.diodes.com/assets/Datasheets/AP3418.pdf",
        "security_intel": {
                "output_voltage": "0.6V–Vin adjustable",
                "enable_pin": "EN (pin 4)",
                "input_range": "2.5V–5.5V",
                "current_max": "1.2A",
                "topology": "Synchronous Buck",
            },
        "description": "1.2A synchronous buck converter",
    },
    {
        "part": "TPS54331DR",
        "aliases": ["TPS54331"],
        "category": "power",
        "manufacturer": "Texas Instruments",
        "package": "SOIC8",
        "datasheet": "https://www.ti.com/lit/ds/symlink/tps54331.pdf",
        "security_intel": {
                "output_voltage": "0.8V–25V adjustable",
                "enable_pin": "EN (pin 3)",
                "input_range": "3.5V–28V",
                "current_max": "3A",
                "topology": "Synchronous Buck",
            },
        "description": "3A 28V input synchronous buck converter",
    },
    {
        "part": "LM2596S-5.0",
        "aliases": ["LM2596", "LM2596S"],
        "category": "power",
        "manufacturer": "Texas Instruments",
        "package": "TO-263-5",
        "datasheet": "https://www.ti.com/lit/ds/symlink/lm2596.pdf",
        "security_intel": {
                "output_voltage": "5.0V fixed",
                "enable_pin": "ON/OFF (pin 5, active low)",
                "input_range": "7V–40V",
                "current_max": "3A",
                "topology": "Buck",
            },
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
        "security_intel": {"interface": "USB 2.0 Full-Speed → UART", "baud_max": "2Mbps", "debug_relevance": "UART console access — check for serial boot loaders"},
        "description": "USB-to-UART bridge",
    },
    {
        "part": "CH340C",
        "aliases": ["CH340C"],
        "category": "usb",
        "manufacturer": "WCH",
        "package": "SOP16",
        "datasheet": "https://www.wch-ic.com/downloads/CH340DS1_PDF.html",
        "security_intel": {"interface": "USB 2.0 Full-Speed → UART (no ext crystal)", "baud_max": "2Mbps", "debug_relevance": "UART console access — check for serial boot loaders"},
        "description": "USB-to-UART with internal crystal",
    },
    {
        "part": "CH340K",
        "aliases": ["CH340K"],
        "category": "usb",
        "manufacturer": "WCH",
        "package": "ESSOP10",
        "datasheet": "https://www.wch-ic.com/downloads/CH340DS1_PDF.html",
        "security_intel": {"interface": "USB 2.0 Full-Speed → UART", "baud_max": "2Mbps", "debug_relevance": "UART console access — compact form factor"},
        "description": "USB-to-UART compact package",
    },
    {
        "part": "FT232RL",
        "aliases": ["FT232", "FT232R", "FTDI"],
        "category": "usb",
        "manufacturer": "FTDI",
        "package": "SSOP28",
        "datasheet": "https://ftdichip.com/wp-content/uploads/2020/08/DS_FT232R.pdf",
        "security_intel": {"interface": "USB 2.0 Full-Speed → UART/FIFO", "baud_max": "3Mbps", "debug_relevance": "UART console — also supports bit-bang GPIO for SPI/I2C"},
        "description": "USB-to-UART/FIFO, 3Mbaud",
    },
    {
        "part": "FT2232H",
        "aliases": ["FT2232", "FT2232H"],
        "category": "usb",
        "manufacturer": "FTDI",
        "package": "LQFP64",
        "datasheet": "https://ftdichip.com/wp-content/uploads/2020/07/DS_FT2232H.pdf",
        "security_intel": {"interface": "USB 2.0 Hi-Speed → dual UART/FIFO/SPI/I2C/JTAG", "baud_max": "12Mbps", "debug_relevance": "JTAG/SWD adapter — Channel A: MPSSE (JTAG), Channel B: UART. OpenOCD compatible"},
        "description": "Dual USB HS UART/FIFO/SPI/I2C/JTAG adapter",
    },
    {
        "part": "FT4232H",
        "aliases": ["FT4232", "FT4232H"],
        "category": "usb",
        "manufacturer": "FTDI",
        "package": "LQFP64",
        "datasheet": "https://ftdichip.com/wp-content/uploads/2020/07/DS_FT4232H.pdf",
        "security_intel": {"interface": "USB 2.0 Hi-Speed → quad UART", "baud_max": "12Mbps", "debug_relevance": "Multi-channel debug — Channels A/B: MPSSE capable (JTAG/SPI), C/D: UART only"},
        "description": "Quad USB HS UART adapter",
    },
    {
        "part": "CP2102N",
        "aliases": ["CP2102", "CP210X", "CP2102N"],
        "category": "usb",
        "manufacturer": "Silicon Labs",
        "package": "QFN28",
        "datasheet": "https://www.silabs.com/documents/public/data-sheets/CP2102-9.pdf",
        "security_intel": {"interface": "USB 2.0 Full-Speed → UART", "baud_max": "3Mbps", "debug_relevance": "UART console access — GPIO available for hardware flow control"},
        "description": "USB-to-UART single chip bridge",
    },
    {
        "part": "CP2104",
        "aliases": ["CP2104"],
        "category": "usb",
        "manufacturer": "Silicon Labs",
        "package": "QFN24",
        "datasheet": "https://www.silabs.com/documents/public/data-sheets/cp2104.pdf",
        "security_intel": {"interface": "USB 2.0 Full-Speed → UART + 4 GPIO", "baud_max": "2Mbps", "debug_relevance": "UART + GPIO — GPIOs can control BOOT0/RESET for auto-programming"},
        "description": "Single-chip USB-to-UART with 4 GPIO",
    },
    {
        "part": "MAX3232ECPWR",
        "aliases": ["MAX3232", "MAX232"],
        "category": "usb",
        "manufacturer": "Maxim",
        "package": "TSSOP16",
        "datasheet": "https://datasheets.maximintegrated.com/en/ds/MAX3222-MAX3241.pdf",
        "security_intel": {"interface": "RS-232 level shifter (3.3V logic ↔ ±6V RS-232)", "baud_max": "250kbps", "debug_relevance": "RS-232 serial console — common on industrial/networking equipment"},
        "description": "3V RS-232 transceiver, 2 TX / 2 RX",
    },
    {
        "part": "MAX232CPE",
        "aliases": ["MAX232CPE", "MAX232E"],
        "category": "usb",
        "manufacturer": "Maxim",
        "package": "PDIP16",
        "datasheet": "https://datasheets.maximintegrated.com/en/ds/MAX220-MAX249.pdf",
        "security_intel": {"interface": "RS-232 level shifter (5V logic ↔ ±9V RS-232)", "baud_max": "120kbps", "debug_relevance": "RS-232 serial console — presence indicates legacy serial management port"},
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
        "security_intel": {
                "interface": "SPI (modes 0, 3) / Dual / Quad",
                "read_cmd": "0x03 (Read), 0x0B (Fast Read)",
                "jedec_id": "0xEF4018",
                "write_protect_pin": "WP# (pin 3)",
                "capacity": "128Mbit (16MB)",
                "flashrom_support": "Yes — flashrom -p <programmer> -c W25Q128.V",
            },
        "description": "128Mbit SPI NOR Flash",
    },
    {
        "part": "W25Q64JV",
        "aliases": ["W25Q64", "25Q64"],
        "category": "flash",
        "manufacturer": "Winbond",
        "package": "SOP8",
        "datasheet": "https://www.winbond.com/resource-files/w25q64jv%20revj%2003272018%20plus.pdf",
        "security_intel": {
                "interface": "SPI (modes 0, 3) / Dual / Quad",
                "read_cmd": "0x03 (Read), 0x0B (Fast Read)",
                "jedec_id": "0xEF4017",
                "write_protect_pin": "WP# (pin 3)",
                "capacity": "64Mbit (8MB)",
                "flashrom_support": "Yes — flashrom -p <programmer> -c W25Q64.V",
            },
        "description": "64Mbit SPI NOR Flash",
    },
    {
        "part": "W25Q32JV",
        "aliases": ["W25Q32", "25Q32"],
        "category": "flash",
        "manufacturer": "Winbond",
        "package": "SOP8",
        "datasheet": "https://www.winbond.com/resource-files/w25q32jv%20revg%2003272018%20plus.pdf",
        "security_intel": {
                "interface": "SPI (modes 0, 3) / Dual / Quad",
                "read_cmd": "0x03 (Read), 0x0B (Fast Read)",
                "jedec_id": "0xEF4016",
                "write_protect_pin": "WP# (pin 3)",
                "capacity": "32Mbit (4MB)",
                "flashrom_support": "Yes — flashrom -p <programmer> -c W25Q32.V",
            },
        "description": "32Mbit SPI NOR Flash",
    },
    {
        "part": "AT25SF128A",
        "aliases": ["AT25SF128", "AT25SF"],
        "category": "flash",
        "manufacturer": "Adesto",
        "package": "SOP8",
        "datasheet": "https://www.adestotech.com/wp-content/uploads/DS-AT25SF128A_047.pdf",
        "security_intel": {
                "interface": "SPI (modes 0, 3) / Dual / Quad",
                "read_cmd": "0x03 (Read), 0x0B (Fast Read)",
                "jedec_id": "0x1F8901",
                "write_protect_pin": "WP# (pin 3)",
                "capacity": "128Mbit (16MB)",
                "flashrom_support": "Yes — flashrom -p <programmer>",
            },
        "description": "128Mbit SPI Flash, industrial grade",
    },
    {
        "part": "MX25L12835F",
        "aliases": ["MX25L128", "MX25L12835"],
        "category": "flash",
        "manufacturer": "Macronix",
        "package": "SOP8",
        "datasheet": "https://www.macronix.com/Lists/Datasheet/Attachments/7395/MX25L12835F,%203V,%20128Mb,%20v1.6.pdf",
        "security_intel": {
                "interface": "SPI (modes 0, 3) / Dual / Quad",
                "read_cmd": "0x03 (Read), 0x0B (Fast Read)",
                "jedec_id": "0xC22018",
                "write_protect_pin": "WP# (pin 3)",
                "capacity": "128Mbit (16MB)",
                "flashrom_support": "Yes — flashrom -p <programmer> -c MX25L12835F/MX25L12845E/MX25L12865E",
            },
        "description": "128Mbit SPI NOR Flash, 3V",
    },
    {
        "part": "SST25VF016B",
        "aliases": ["SST25VF016", "SST25"],
        "category": "flash",
        "manufacturer": "Microchip",
        "package": "SOP8",
        "datasheet": "https://ww1.microchip.com/downloads/en/DeviceDoc/S71271_04.pdf",
        "security_intel": {
                "interface": "SPI (modes 0, 3)",
                "read_cmd": "0x03 (Read), 0x0B (Fast Read)",
                "jedec_id": "0xBF2541",
                "write_protect_pin": "WP# (pin 3)",
                "capacity": "16Mbit (2MB)",
                "flashrom_support": "Yes — flashrom -p <programmer> -c SST25VF016B",
            },
        "description": "16Mbit SPI Serial Flash",
    },
    {
        "part": "GD25Q64",
        "aliases": ["GD25Q64", "25Q64GD"],
        "category": "flash",
        "manufacturer": "GigaDevice",
        "package": "SOP8",
        "datasheet": "https://www.gigadevice.com/datasheet/gd25q64c/",
        "security_intel": {
                "interface": "SPI (modes 0, 3) / Dual / Quad",
                "read_cmd": "0x03 (Read), 0x0B (Fast Read)",
                "jedec_id": "0xC84017",
                "write_protect_pin": "WP# (pin 3)",
                "capacity": "64Mbit (8MB)",
                "flashrom_support": "Yes — flashrom -p <programmer> -c GD25Q64(B)",
            },
        "description": "64Mbit SPI NOR Flash",
    },
    {
        "part": "IS25LP128F",
        "aliases": ["IS25LP128", "IS25LP"],
        "category": "flash",
        "manufacturer": "ISSI",
        "package": "SOP8",
        "datasheet": "https://www.issi.com/WW/pdf/IS25LP128F.pdf",
        "security_intel": {
                "interface": "SPI (modes 0, 3) / Dual / Quad",
                "read_cmd": "0x03 (Read), 0x0B (Fast Read)",
                "jedec_id": "0x9D6018",
                "write_protect_pin": "WP# (pin 3)",
                "capacity": "128Mbit (16MB)",
                "flashrom_support": "Yes — flashrom -p <programmer>",
            },
        "description": "128Mbit SPI NOR Flash, 133MHz",
    },
    {
        "part": "S25FL256SAGMFI001",
        "aliases": ["S25FL256", "S25FL256L"],
        "category": "flash",
        "manufacturer": "Infineon",
        "package": "SOP8",
        "datasheet": "https://www.infineon.com/dgdl/Infineon-S25FL256L-DataSheet-v05_00-EN.pdf",
        "security_intel": {
                "interface": "SPI (modes 0, 3) / Dual / Quad",
                "read_cmd": "0x03 (Read), 0x0B (Fast Read), 0x13 (4-byte addr)",
                "jedec_id": "0x010219",
                "write_protect_pin": "WP# (pin 3)",
                "capacity": "256Mbit (32MB)",
                "flashrom_support": "Yes — flashrom -p <programmer> -c S25FL256S......0",
            },
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
        "security_intel": {"interface": "I2C (addr 0x50–0x57)", "write_protect_pin": "WP (pin 7)", "capacity": "256Kbit (32KB)"},
        "description": "256Kbit I2C EEPROM",
    },
    {
        "part": "AT24C02",
        "aliases": ["AT24C02", "24C02"],
        "category": "eeprom",
        "manufacturer": "Microchip",
        "package": "SOIC8",
        "datasheet": "https://ww1.microchip.com/downloads/en/DeviceDoc/doc0180.pdf",
        "security_intel": {"interface": "I2C (addr 0x50–0x57)", "write_protect_pin": "WP (pin 7)", "capacity": "2Kbit (256B)"},
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
        "security_intel": {
                "interface": "SPI",
                "frequency": "2.4GHz ISM",
                "protocol": "Proprietary / ShockBurst",
                "debug_relevance": "Wireless sniffing — known protocol weaknesses (no encryption by default)",
            },
        "description": "2.4GHz RF transceiver, -6dBm to 0dBm",
    },
    {
        "part": "CC1101",
        "aliases": ["CC1101"],
        "category": "rf",
        "manufacturer": "Texas Instruments",
        "package": "QFN20",
        "datasheet": "https://www.ti.com/lit/ds/symlink/cc1101.pdf",
        "security_intel": {
                "interface": "SPI",
                "frequency": "315/433/868/915MHz Sub-GHz",
                "protocol": "FSK/OOK/MSK",
                "debug_relevance": "Sub-GHz RF — can be used for replay attacks if OOK; popular in garage/alarm systems",
            },
        "description": "Sub-1GHz RF transceiver, 315/433/868/915 MHz",
    },
    {
        "part": "SX1276MB1MAS",
        "aliases": ["SX1276", "SX1276MB"],
        "category": "rf",
        "manufacturer": "Semtech",
        "package": "TQFN28",
        "datasheet": "https://semtech.my.salesforce.com/sfc/p/#E0000000JelG/a/2R000000HT76/7Nka9W5WgugoZe.xwIHJy6ebj1hW8UJ.CSjV7p3nSyw",
        "security_intel": {
                "interface": "SPI",
                "frequency": "868/915MHz",
                "protocol": "LoRa / FSK",
                "debug_relevance": "Long-range RF — LoRa packets can be intercepted with SDR",
            },
        "description": "LoRa 868/915 MHz transceiver",
    },
    {
        "part": "SX1262",
        "aliases": ["SX1262"],
        "category": "rf",
        "manufacturer": "Semtech",
        "package": "HCLGA24",
        "datasheet": "https://semtech.my.salesforce.com/sfc/p/#E0000000JelG/a/2R000000Un7F/bOssk1oDB7V.pXj1sEKR_T8G0gQSrGXxFcVSxX2WEJM",
        "security_intel": {
                "interface": "SPI",
                "frequency": "150–960MHz",
                "protocol": "LoRa / (G)FSK",
                "debug_relevance": "Next-gen LoRa — improved crypto support but still application-layer dependent",
            },
        "description": "LoRa 868/915 MHz next-gen transceiver",
    },
    {
        "part": "RTL8720DN",
        "aliases": ["RTL8720D", "RTL8720DN"],
        "category": "rf",
        "manufacturer": "Realtek",
        "package": "QFN48",
        "datasheet": "https://www.realtek.com/en/products/wireless-lan-ics/item/rtl8720dn",
        "security_intel": {
                "interface": "SDIO/UART/SPI",
                "frequency": "2.4GHz + 5GHz",
                "protocol": "WiFi 5 + BT 5",
                "debug_relevance": "Dual-band WiFi — look for UART debug console on secondary interface",
            },
        "description": "Dual-band WiFi5+BT5 combo, ARM Cortex-M33+M0",
    },
    {
        "part": "CYW43455",
        "aliases": ["CYW43455", "BCM43455"],
        "category": "rf",
        "manufacturer": "Infineon",
        "package": "WLBGA",
        "datasheet": "https://www.infineon.com/cms/en/product/wireless-connectivity/airoc-wi-fi-plus-bluetooth-combos/cyw43455/",
        "security_intel": {
                "interface": "SDIO",
                "frequency": "2.4GHz + 5GHz",
                "protocol": "WiFi 5 + BT 5",
                "debug_relevance": "RPi WiFi combo — firmware loaded at boot from host; monitor SDIO bus",
            },
        "description": "WiFi5+BT5 combo (Raspberry Pi CM4/Zero2W)",
    },
    {
        "part": "MT7688AN",
        "aliases": ["MT7688", "MT7688AN"],
        "category": "rf",
        "manufacturer": "MediaTek",
        "package": "QFN88",
        "datasheet": "https://labs.mediatek.com/fileMedia/download/9ef51e98-49b1-489a-b27e-391bac9f7bf3",
        "security_intel": {
                "interface": "PCIe/USB/UART/SPI",
                "frequency": "2.4GHz",
                "protocol": "WiFi 4 (802.11n)",
                "debug_relevance": "Linux-based SoC — UART console at 57600 baud typical; U-Boot accessible",
            },
        "description": "MIPS 580MHz WiFi SoC, 802.11n",
    },
    {
        "part": "ATWILC1000B-MU",
        "aliases": ["ATWILC1000", "WILC1000"],
        "category": "rf",
        "manufacturer": "Microchip",
        "package": "QFN40",
        "datasheet": "https://ww1.microchip.com/downloads/en/DeviceDoc/ATWILC1000-MR110xB-DS40002158B.pdf",
        "security_intel": {
                "interface": "SPI/SDIO",
                "frequency": "2.4GHz",
                "protocol": "WiFi (802.11 b/g/n)",
                "debug_relevance": "WiFi link controller — host-controlled, FW loaded from host SPI flash",
            },
        "description": "IEEE 802.11 b/g/n WiFi link controller",
    },
    {
        "part": "ATECC608A",
        "aliases": ["ATECC608", "ATECC608A"],
        "category": "secure_element",
        "manufacturer": "Microchip",
        "package": "UDFN8",
        "datasheet": "https://ww1.microchip.com/downloads/en/DeviceDoc/ATECC608A-TFLXTLSS-CryptoAuthentication-DS40002007B.pdf",
        "security_intel": {
                "interface": "I2C (0x60 default)",
                "certification": "FIPS-compliant",
                "key_storage": "16 key slots, hardware ECDH/ECDSA P-256",
                "debug_relevance": "Crypto engine — if I2C bus is accessible, slot configs can be read (but keys can't)",
            },
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
        "security_intel": {"interface": "I2C (0x76/0x77) or SPI", "debug_relevance": "Environmental sensor — I2C/SPI bus presence indicator"},
        "description": "Temp/humidity/pressure combo sensor, I2C/SPI",
    },
    {
        "part": "BMP280",
        "aliases": ["BMP280"],
        "category": "sensor",
        "manufacturer": "Bosch",
        "package": "LGA-8",
        "datasheet": "https://www.bosch-sensortec.com/media/boschsensortec/downloads/datasheets/bst-bmp280-ds001.pdf",
        "security_intel": {"interface": "I2C or SPI", "debug_relevance": "Sensor — I2C/SPI bus presence indicator"},
        "description": "Barometric pressure/temperature sensor, I2C/SPI",
    },
    {
        "part": "MPU-6050",
        "aliases": ["MPU6050", "MPU-6050"],
        "category": "sensor",
        "manufacturer": "TDK InvenSense",
        "package": "QFN24",
        "datasheet": "https://invensense.tdk.com/wp-content/uploads/2015/02/MPU-6000-Datasheet1.pdf",
        "security_intel": {"interface": "I2C or SPI", "debug_relevance": "Sensor — I2C/SPI bus presence indicator"},
        "description": "6-axis IMU (3-axis gyro + 3-axis accel), I2C",
    },
    {
        "part": "ADXL345",
        "aliases": ["ADXL345"],
        "category": "sensor",
        "manufacturer": "Analog Devices",
        "package": "LGA-14",
        "datasheet": "https://www.analog.com/media/en/technical-documentation/data-sheets/adxl345.pdf",
        "security_intel": {"interface": "I2C or SPI", "debug_relevance": "Sensor — I2C/SPI bus presence indicator"},
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
        "security_intel": {"interface": "I2C or SPI", "debug_relevance": "Sensor — I2C/SPI bus presence indicator"},
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
        "security_intel": {"interface": "I2S", "debug_relevance": "Audio codec — I2S bus presence indicator"},
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
        "security_intel": {
                "interface": "SPI (TPM 2.0 PTP)",
                "certification": "FIPS 140-2 Level 1, CC EAL4+",
                "key_storage": "RSA-2048, ECC P-256, SHA-256 PCR banks",
                "attestation": "Remote attestation via TPM2_Quote, Endorsement Key (EK) certificate",
            },
        "description": "TPM 2.0, SPI interface, FIPS 140-2 certified",
    },
    {
        "part": "NPCT750",
        "aliases": ["NPCT750", "NPCT750A", "NUVOTON NPCT750"],
        "category": "tpm",
        "manufacturer": "Nuvoton",
        "package": "QFP-32",
        "datasheet": "https://www.nuvoton.com/resource-files/NPCT750_DS_Ver1.0.pdf",
        "security_intel": {
                "interface": "LPC (TPM 2.0 PTP)",
                "certification": "FIPS 140-2 Level 2",
                "key_storage": "RSA-2048, ECC P-256, SHA-256 PCR banks",
                "attestation": "Remote attestation, platform-specific EK",
            },
        "description": "TPM 2.0, LPC interface",
    },
    {
        "part": "ST33TPHF2ESPI",
        "aliases": ["ST33TPHF2ESPI", "ST33TPH", "ST33"],
        "category": "tpm",
        "manufacturer": "STMicroelectronics",
        "package": "UFQFPN-32",
        "datasheet": "https://www.st.com/resource/en/datasheet/st33tphf2espi.pdf",
        "security_intel": {
                "interface": "SPI (TPM 2.0 PTP)",
                "certification": "CC EAL4+",
                "key_storage": "RSA-2048, ECC P-256/P-384, SHA-256/384 PCR banks",
                "attestation": "Remote attestation via TPM2_Quote, ST-provided EK cert",
            },
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
        "security_intel": {
                "interface": "I2C (configurable address)",
                "certification": "CC EAL 6+ (JCOP 4 SE)",
                "key_storage": "RSA up to 4096, ECC up to P-521, AES-256",
                "debug_relevance": "High-assurance SE — applet-based; I2C bus sniffing reveals APDUs but not keys",
            },
        "description": "Secure Element, I2C, IoT security middleware, CC EAL 6+",
    },
    {
        "part": "ATECC608B",
        "aliases": ["ATECC608B", "ATECC608"],
        "category": "secure_element",
        "manufacturer": "Microchip",
        "package": "UDFN-8",
        "datasheet": "https://ww1.microchip.com/downloads/en/DeviceDoc/ATECC608B-CryptoAuthentication-Device-Summary-Data-Sheet-DS40002239B.pdf",
        "security_intel": {
                "interface": "I2C (0x6A default, configurable)",
                "certification": "FIPS-compliant",
                "key_storage": "16 key slots, hardware ECDH/ECDSA P-256",
                "debug_relevance": "Crypto engine — B revision adds Trust&GO pre-provisioned mode",
            },
        "description": "CryptoAuthentication device, ECDH/ECDSA, hardware key storage (B revision)",
    },
    {
        "part": "SLS32AIA",
        "aliases": ["SLS32AIA", "SLS32", "INFINEON SLS32"],
        "category": "secure_element",
        "manufacturer": "Infineon",
        "package": "SPI",
        "datasheet": "https://www.infineon.com/cms/en/product/security-smart-card-solutions/optiga-embedded-security-solutions/optiga-trust/",
        "security_intel": {
                "interface": "SPI (configurable)",
                "certification": "CC EAL 5+ / NIST SP 800-90A",
                "key_storage": "Hardware-bound ECC keys",
                "debug_relevance": "OPTIGA Trust Anchor — SPI interface; look for platform binding certificates",
            },
        "description": "OPTIGA Trust Anchor, SPI, mutual authentication",
    },
    {
        "part": "STSAFE-A110",
        "aliases": ["STSAFE-A110", "STSAFEA110", "STSAFE"],
        "category": "secure_element",
        "manufacturer": "STMicroelectronics",
        "package": "SO8N",
        "datasheet": "https://www.st.com/resource/en/datasheet/stsafe-a110.pdf",
        "security_intel": {
                "interface": "I2C (0x20 default)",
                "certification": "CC EAL5+ (STSAFE platform)",
                "key_storage": "ECC P-256/P-384, pre-provisioned device certificate",
                "debug_relevance": "TLS auth element — I2C commands use ISO 7816 APDU format",
            },
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
        "security_intel": {
                "config_interface": ["JTAG", "SPI (Master/Slave)", "BPI", "SelectMAP"],
                "jtag_chain": True,
                "bitstream_format": ".bit / .bin (Vivado)",
                "toolchain": "Xilinx Vivado (also f4pga open-source)",
                "lut_count": 20800,
                "debug_relevance": "Bitstream readback possible if PROGRAM.B not disabled; check JTAG chain for idcode 0x0362D093",
            },
        "description": "Artix-7 FPGA, 33280 LUTs, PCIe, 6.6Gb/s transceivers",
    },
    {
        "part": "XC6SLX9",
        "aliases": ["XC6SLX9", "SPARTAN-6", "SPARTAN6", "XC6SLX9-2"],
        "category": "fpga",
        "manufacturer": "Xilinx",
        "package": "TQFP-144",
        "datasheet": "https://www.xilinx.com/support/documentation/data_sheets/ds160.pdf",
        "security_intel": {
                "config_interface": ["JTAG", "SPI (Master)", "BPI"],
                "jtag_chain": True,
                "bitstream_format": ".bit / .bin (ISE)",
                "toolchain": "Xilinx ISE (legacy)",
                "lut_count": 5720,
                "debug_relevance": "Spartan-6 bitstream partially reverse-engineerable; check JTAG idcode 0x04001093",
            },
        "description": "Spartan-6 FPGA, 9152 LUTs, low-power, LPDDR support",
    },
    {
        "part": "iCE40UP5K",
        "aliases": ["ICE40UP5K", "ICE40", "ICE40UP5K-SG48"],
        "category": "fpga",
        "manufacturer": "Lattice",
        "package": "QFN-48",
        "datasheet": "https://www.latticesemi.com/view_document?document_id=51968",
        "security_intel": {
                "config_interface": ["SPI (Master)", "NVCM (one-time)"],
                "jtag_chain": False,
                "bitstream_format": ".bin (icestorm/nextpnr)",
                "toolchain": "Open-source: Yosys + nextpnr-ice40 + icestorm",
                "lut_count": 5280,
                "debug_relevance": "Fully open-source reversible — icestorm can decompile bitstream back to netlist",
            },
        "description": "iCE40 UltraPlus FPGA, 5280 LUTs, DSP, SPRAM, open-source toolchain",
    },
    {
        "part": "10M08SAE144C8G",
        "aliases": ["MAX10", "10M08", "INTEL MAX10", "MAX10 10M08"],
        "category": "fpga",
        "manufacturer": "Intel",
        "package": "EQFP-144",
        "datasheet": "https://www.intel.com/content/www/us/en/programmable/documentation/mcn1397700832153.html",
        "security_intel": {
                "config_interface": ["JTAG", "AS (Active Serial)"],
                "jtag_chain": True,
                "bitstream_format": ".sof / .pof (Quartus)",
                "toolchain": "Intel Quartus Prime Lite (free)",
                "lut_count": 8000,
                "debug_relevance": "Non-volatile config — JTAG can read/write internal flash; idcode via JTAG scan",
            },
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
        "security_intel": {
                "mdio_phy_addr": "Configurable via CONFIG[2:0] pins (0–7)",
                "management_interface": "MDIO/MDC (Clause 22 + 45)",
                "rgmii_voltage": "1.8V / 2.5V / 3.3V (configurable)",
                "debug_relevance": "Packet capture via RGMII tap; MDIO registers accessible for link status/config",
            },
        "description": "Gigabit Ethernet PHY, SGMII/RGMII/MDIO, copper+fiber combo",
    },
    {
        "part": "BCM5482",
        "aliases": ["BCM5482", "BROADCOM BCM5482"],
        "category": "ethernet",
        "manufacturer": "Broadcom",
        "package": "BGA-196",
        "datasheet": "https://www.broadcom.com/products/ethernet-connectivity/phy-and-poe/copper/gigabit/bcm5482",
        "security_intel": {
                "mdio_phy_addr": "Configurable (dual PHY: addr N and N+1)",
                "management_interface": "MDIO/MDC (Clause 22)",
                "rgmii_voltage": "2.5V / 3.3V",
                "debug_relevance": "Dual-port PHY — can mirror traffic between ports via MDIO register config",
            },
        "description": "Dual-port Gigabit Ethernet PHY, RGMII, SerDes",
    },
    {
        "part": "RTL8211F",
        "aliases": ["RTL8211F", "RTL8211FD", "REALTEK RTL8211F"],
        "category": "ethernet",
        "manufacturer": "Realtek",
        "package": "QFN-48",
        "datasheet": "https://www.realtek.com/en/products/communications-network-ics/item/rtl8211f-i-cg",
        "security_intel": {
                "mdio_phy_addr": "Configurable via PHYAD[2:0] pins",
                "management_interface": "MDIO/MDC (Clause 22 + 45)",
                "rgmii_voltage": "3.3V",
                "debug_relevance": "Common Linux PHY — kernel driver well-documented; MDIO registers at standard addresses",
            },
        "description": "Gigabit Ethernet PHY, RGMII/MII/GMII, MDIO/MDC",
    },
    # -----------------------------------------------------------------------
    # Network — CAN/LIN/FlexRay transceivers
    # -----------------------------------------------------------------------
    {
        "part": "TJA1050",
        "aliases": ["TJA1050", "TJA1050T"],
        "category": "network",
        "manufacturer": "NXP",
        "package": "SOIC8",
        "datasheet": "https://www.nxp.com/docs/en/data-sheet/TJA1050.pdf",
        "security_intel": {
            "interface": "CAN 2.0A/B",
            "logic_voltage": "5V",
            "debug_relevance": "CAN transceiver — attach CANH/CANL probes for bus sniffing; no debug auth",
        },
        "description": "High-speed CAN transceiver, 1Mbps, SOIC8",
    },
    {
        "part": "MCP2515",
        "aliases": ["MCP2515", "MCP2515-I/SO"],
        "category": "network",
        "manufacturer": "Microchip",
        "package": "SOIC18",
        "datasheet": "https://ww1.microchip.com/downloads/en/DeviceDoc/MCP2515-Stand-Alone-CAN-Controller-with-SPI-20001801J.pdf",
        "security_intel": {
            "interface": "CAN 2.0B via SPI",
            "logic_voltage": "2.7V–5.5V",
            "debug_relevance": "SPI-attached CAN controller — SPI MOSI/MISO/SCK accessible for bus replay",
        },
        "description": "Stand-alone CAN controller with SPI interface",
    },
    {
        "part": "SN65HVD230",
        "aliases": ["SN65HVD230", "SN65HVD230D"],
        "category": "network",
        "manufacturer": "Texas Instruments",
        "package": "SOIC8",
        "datasheet": "https://www.ti.com/lit/ds/symlink/sn65hvd230.pdf",
        "security_intel": {
            "interface": "CAN 2.0",
            "logic_voltage": "3.3V",
            "debug_relevance": "3.3V CAN transceiver common in industrial IoT; bus directly sniffable",
        },
        "description": "3.3V CAN bus transceiver, 1Mbps",
    },
    # -----------------------------------------------------------------------
    # PMIC — power management ICs
    # -----------------------------------------------------------------------
    {
        "part": "MAX77620",
        "aliases": ["MAX77620", "MAX77620A"],
        "category": "pmic",
        "manufacturer": "Maxim Integrated",
        "package": "WLP40",
        "datasheet": "https://www.analog.com/media/en/technical-documentation/data-sheets/MAX77620.pdf",
        "security_intel": {
            "interface": "I2C (0x3C)",
            "logic_voltage": "1.8V–3.3V",
            "debug_relevance": "I2C PMIC — address 0x3C; can reconfigure rail voltages to fault system or unlock boot modes",
        },
        "description": "Multi-output PMIC, 4 buck converters + 9 LDOs, I2C",
    },
    {
        "part": "TPS65988",
        "aliases": ["TPS65988", "TPS65988DH"],
        "category": "pmic",
        "manufacturer": "Texas Instruments",
        "package": "VQFN-64",
        "datasheet": "https://www.ti.com/lit/ds/symlink/tps65988.pdf",
        "security_intel": {
            "interface": "I2C, USB PD negotiation",
            "logic_voltage": "3.3V",
            "debug_relevance": "USB PD controller with I2C; PD policy tables sometimes updateable over I2C for voltage injection",
        },
        "description": "Dual-port USB Type-C and USB PD controller",
    },
    {
        "part": "BD71837MWV",
        "aliases": ["BD71837", "BD71837MWV"],
        "category": "pmic",
        "manufacturer": "Rohm Semiconductor",
        "package": "WLCSP60",
        "datasheet": "https://fscdn.rohm.com/en/products/databook/datasheet/ic/power/switching_regulator/bd71837mwv-e.pdf",
        "security_intel": {
            "interface": "I2C",
            "logic_voltage": "1.8V",
            "debug_relevance": "I2C PMIC used in i.MX8 designs; rail manipulation can bypass ROP fuses",
        },
        "description": "8-buck/7-LDO PMIC for i.MX8M, I2C programmable",
    },
    # -----------------------------------------------------------------------
    # Memory — DRAM / NAND / eMMC
    # -----------------------------------------------------------------------
    {
        "part": "MT41K256M16HA",
        "aliases": ["MT41K256M16", "DDR3L", "MT41K256M16HA-125"],
        "category": "memory",
        "manufacturer": "Micron",
        "package": "FBGA96",
        "datasheet": "https://www.micron.com/products/dram/ddr3-sdram",
        "security_intel": {
            "interface": "DDR3L SDRAM",
            "logic_voltage": "1.35V",
            "debug_relevance": "DDR3 DRAM — cold boot attack vector; row hammer exploitable on unmitigated silicon",
        },
        "description": "4Gb DDR3L SDRAM, 1600MHz, x16",
    },
    {
        "part": "KLMAG1JETD",
        "aliases": ["KLMAG1JETD", "eMMC 32GB", "Samsung eMMC"],
        "category": "memory",
        "manufacturer": "Samsung",
        "package": "BGA153",
        "datasheet": "https://semiconductor.samsung.com/consumer-storage/internal-ssd/",
        "security_intel": {
            "interface": "eMMC 5.1 (HS400)",
            "logic_voltage": "1.8V / 3.3V",
            "debug_relevance": "eMMC — replay-protected write protect; boot partition often RO but accessible via CMD0/CMD1 in download mode",
        },
        "description": "32GB eMMC 5.1 NAND flash, HS400",
    },
    {
        "part": "MT29F4G08ABAEA",
        "aliases": ["MT29F4G08", "NAND Flash 512MB"],
        "category": "memory",
        "manufacturer": "Micron",
        "package": "TSOP48",
        "datasheet": "https://www.micron.com/products/nand-flash",
        "security_intel": {
            "interface": "NAND (async, 8-bit)",
            "logic_voltage": "3.3V",
            "debug_relevance": "Parallel NAND — ALE/CLE/WE/RE accessible on TSOP48; clip-on adapters enable offline dump",
        },
        "description": "4Gb SLC NAND Flash, x8, TSOP48",
    },
    # -----------------------------------------------------------------------
    # Display — display drivers and controllers
    # -----------------------------------------------------------------------
    {
        "part": "ILI9341",
        "aliases": ["ILI9341", "ILI9341V"],
        "category": "display",
        "manufacturer": "Ilitek",
        "package": "COF",
        "datasheet": "https://cdn-shop.adafruit.com/datasheets/ILI9341.pdf",
        "security_intel": {
            "interface": "SPI / 8080-I / 8080-II parallel",
            "logic_voltage": "3.3V",
            "debug_relevance": "SPI display driver — intercept MOSI to capture framebuffer; no auth",
        },
        "description": "262K color 240×320 TFT LCD controller, SPI/parallel",
    },
    {
        "part": "SSD1306",
        "aliases": ["SSD1306", "SSD1306Z"],
        "category": "display",
        "manufacturer": "Solomon Systech",
        "package": "COF",
        "datasheet": "https://cdn-shop.adafruit.com/datasheets/SSD1306.pdf",
        "security_intel": {
            "interface": "I2C (0x3C or 0x3D) / SPI",
            "logic_voltage": "1.65V–3.3V",
            "debug_relevance": "OLED driver — I2C address fixed by SA0 pin; trivial to sniff displayed content",
        },
        "description": "128×64 OLED display controller, I2C/SPI",
    },
    {
        "part": "TC358743XBG",
        "aliases": ["TC358743", "TC358743XBG"],
        "category": "display",
        "manufacturer": "Toshiba",
        "package": "BGA100",
        "datasheet": "https://toshiba.semicon-storage.com/info/TC358743XBG_datasheet_en_20150805.pdf",
        "security_intel": {
            "interface": "HDMI 1.4 → MIPI CSI-2",
            "logic_voltage": "1.8V / 3.3V",
            "debug_relevance": "HDMI bridge — HDCP keys stored in EEPROM; CSI-2 output unencrypted after HDCP strip",
        },
        "description": "HDMI 1.4 to MIPI CSI-2 bridge, up to 1080p60",
    },
    # -----------------------------------------------------------------------
    # Automotive — automotive-grade transceivers and controllers
    # -----------------------------------------------------------------------
    {
        "part": "TJA1145",
        "aliases": ["TJA1145", "TJA1145T"],
        "category": "automotive",
        "manufacturer": "NXP",
        "package": "SOIC14",
        "datasheet": "https://www.nxp.com/docs/en/data-sheet/TJA1145.pdf",
        "security_intel": {
            "interface": "CAN FD + SPI",
            "logic_voltage": "3.3V / 5V",
            "debug_relevance": "CAN FD transceiver with SPI config — SPI accessible for mode changes; wake-up filter configurable",
        },
        "description": "Automotive CAN FD transceiver with SPI, partial networking",
    },
    {
        "part": "SPC5748G",
        "aliases": ["SPC5748G", "MPC5748G"],
        "category": "automotive",
        "manufacturer": "NXP",
        "package": "PBGA516",
        "datasheet": "https://www.nxp.com/products/processors-and-microcontrollers/power-architecture/mpc5xxx-microcontrollers/ultra-reliable-mpc57xx-series/mpc5748g-scalable-and-ultra-reliable-mcu-for-automotive-industrial-and-general-purpose-market:MPC5748G",
        "security_intel": {
            "debug_interfaces": ["JTAG", "Nexus Class 3"],
            "boot_mode_pins": ["BOOTCFG[0:1]", "TEST"],
            "readout_protection": "HSM (Hardware Security Module) + lifecycle state",
            "core": "3× Power Architecture e200z4",
            "voltage_range": "3.0V–5.5V",
        },
        "description": "Triple-core Power Architecture MCU, ISO 26262 ASIL-D, CAN/LIN/FlexRay",
    },
    {
        "part": "TCAN4550",
        "aliases": ["TCAN4550", "TCAN4550-Q1"],
        "category": "automotive",
        "manufacturer": "Texas Instruments",
        "package": "WQFN-20",
        "datasheet": "https://www.ti.com/lit/ds/symlink/tcan4550-q1.pdf",
        "security_intel": {
            "interface": "CAN FD + SPI",
            "logic_voltage": "3.3V",
            "debug_relevance": "CAN FD controller/transceiver combo via SPI — full CAN FD bus accessible; register file configurable over SPI",
        },
        "description": "AEC-Q100 CAN FD controller + transceiver combo, SPI host interface",
    },
    # -----------------------------------------------------------------------
    # Automotive MCUs — NXP S32K, TI TMS570 Hercules, Infineon AURIX, Renesas
    # -----------------------------------------------------------------------
    {
        "part": "S32K144",
        "aliases": ["S32K144", "S32K144HFT", "NXP S32K144"],
        "category": "automotive_mcu",
        "manufacturer": "NXP",
        "package": "LQFP100",
        "datasheet": "https://www.nxp.com/docs/en/data-sheet/S32K1XX_DS.pdf",
        "security_intel": {
            "debug_interfaces": ["JTAG", "SWD"],
            "boot_mode_pins": ["RESET_b", "BOOT_CFG"],
            "readout_protection": "Flash security byte (FSEC) + CSEc (AES-128 HSM)",
            "core": "ARM Cortex-M4F @ 112MHz",
            "voltage_range": "2.7V–5.5V",
        },
        "description": "Automotive Cortex-M4F, 512KB Flash, ASIL-B, CAN FD",
    },
    {
        "part": "S32K146",
        "aliases": ["S32K146", "S32K146HFT", "NXP S32K146"],
        "category": "automotive_mcu",
        "manufacturer": "NXP",
        "package": "LQFP144",
        "datasheet": "https://www.nxp.com/docs/en/data-sheet/S32K1XX_DS.pdf",
        "security_intel": {
            "debug_interfaces": ["JTAG", "SWD"],
            "boot_mode_pins": ["RESET_b", "BOOT_CFG"],
            "readout_protection": "Flash security byte (FSEC) + CSEc (AES-128 HSM)",
            "core": "ARM Cortex-M4F @ 112MHz",
            "voltage_range": "2.7V–5.5V",
        },
        "description": "Automotive Cortex-M4F, 1MB Flash, ASIL-B, CAN FD x3",
    },
    {
        "part": "S32K148",
        "aliases": ["S32K148", "S32K148HFT", "NXP S32K148"],
        "category": "automotive_mcu",
        "manufacturer": "NXP",
        "package": "LQFP176",
        "datasheet": "https://www.nxp.com/docs/en/data-sheet/S32K1XX_DS.pdf",
        "security_intel": {
            "debug_interfaces": ["JTAG", "SWD"],
            "boot_mode_pins": ["RESET_b", "BOOT_CFG"],
            "readout_protection": "Flash security byte (FSEC) + CSEc (AES-128 HSM)",
            "core": "ARM Cortex-M4F @ 112MHz",
            "voltage_range": "2.7V–5.5V",
        },
        "description": "Automotive Cortex-M4F, 2MB Flash, ASIL-B, Ethernet + CAN FD",
    },
    {
        "part": "S32K344",
        "aliases": ["S32K344", "S32K3", "NXP S32K344"],
        "category": "automotive_mcu",
        "manufacturer": "NXP",
        "package": "MAPBGA172",
        "datasheet": "https://www.nxp.com/docs/en/data-sheet/S32K3xx_DS.pdf",
        "security_intel": {
            "debug_interfaces": ["JTAG", "SWD"],
            "boot_mode_pins": ["RESET_b", "BOOT_MODE"],
            "readout_protection": "HSE (Hardware Security Engine) + lifecycle states",
            "core": "Lockstep ARM Cortex-M7 @ 240MHz",
            "voltage_range": "2.7V–5.5V",
        },
        "description": "Automotive lockstep Cortex-M7, 4MB Flash, ASIL-D, HSE",
    },
    {
        "part": "TMS570LS3137",
        "aliases": ["TMS570LS3137", "TMS570", "Hercules"],
        "category": "automotive_mcu",
        "manufacturer": "Texas Instruments",
        "package": "PGE144",
        "datasheet": "https://www.ti.com/lit/ds/symlink/tms570ls3137.pdf",
        "security_intel": {
            "debug_interfaces": ["JTAG (cJTAG)", "ETM"],
            "boot_mode_pins": ["nRST", "FLASH_CFG"],
            "readout_protection": "Flash ECC + JTAG security module (lockable)",
            "core": "Dual lockstep ARM Cortex-R4F @ 180MHz",
            "voltage_range": "1.2V core / 3.3V I/O",
        },
        "description": "Hercules safety MCU, dual-core Cortex-R4F lockstep, ASIL-D",
    },
    {
        "part": "TMS570LS1224",
        "aliases": ["TMS570LS1224", "TMS570LS12"],
        "category": "automotive_mcu",
        "manufacturer": "Texas Instruments",
        "package": "PGE144",
        "datasheet": "https://www.ti.com/lit/ds/symlink/tms570ls1224.pdf",
        "security_intel": {
            "debug_interfaces": ["JTAG (cJTAG)", "ETM"],
            "boot_mode_pins": ["nRST", "FLASH_CFG"],
            "readout_protection": "Flash ECC + JTAG security module (lockable)",
            "core": "Dual lockstep ARM Cortex-R4F @ 180MHz",
            "voltage_range": "1.2V core / 3.3V I/O",
        },
        "description": "Hercules safety MCU, 1.25MB Flash, ASIL-D, FlexRay/CAN",
    },
    {
        "part": "RM57L843",
        "aliases": ["RM57L843", "RM57L"],
        "category": "automotive_mcu",
        "manufacturer": "Texas Instruments",
        "package": "ZWT337",
        "datasheet": "https://www.ti.com/lit/ds/symlink/rm57l843.pdf",
        "security_intel": {
            "debug_interfaces": ["JTAG (cJTAG)", "ETM"],
            "boot_mode_pins": ["nRST"],
            "readout_protection": "Flash ECC + JTAG password",
            "core": "Dual lockstep ARM Cortex-R5F @ 330MHz",
            "voltage_range": "1.2V core / 3.3V I/O",
        },
        "description": "Hercules industrial-safety MCU, dual lockstep R5F, SIL-3",
    },
    {
        "part": "TC275T",
        "aliases": ["TC275", "TC275T", "AURIX TC275"],
        "category": "automotive_mcu",
        "manufacturer": "Infineon",
        "package": "LFBGA292",
        "datasheet": "https://www.infineon.com/dgdl/Infineon-AURIX_TC27x_D-Step-DataSheet-v01_00-EN.pdf",
        "security_intel": {
            "debug_interfaces": ["JTAG", "DAP", "Cerberus debug"],
            "boot_mode_pins": ["HWCFG[6:0]"],
            "readout_protection": "HSM (TriCore secure module) + UCB lifecycle protection",
            "core": "Triple TriCore 1.6P @ 200MHz",
            "voltage_range": "3.3V / 5V",
        },
        "description": "AURIX 2G triple-core TriCore, 4MB Flash, ASIL-D, HSM",
    },
    {
        "part": "R7F701649",
        "aliases": ["R7F701649", "RH850/F1KH"],
        "category": "automotive_mcu",
        "manufacturer": "Renesas",
        "package": "LFBGA292",
        "datasheet": "https://www.renesas.com/us/en/products/microcontrollers-microprocessors/rh850-automotive-mcus/rh850f1kh-d8-rh850f1kh-and-rh850f1km-d8-microcontrollers-body-and-gateway-systems",
        "security_intel": {
            "debug_interfaces": ["LPD (Renesas debug)", "JTAG (test mode)"],
            "boot_mode_pins": ["FLMD0", "FLMD1"],
            "readout_protection": "OCD security ID (16-byte authentication)",
            "core": "Dual G3KH @ 240MHz",
            "voltage_range": "3.3V / 5V",
        },
        "description": "RH850 automotive MCU, dual-core, FlexRay/CAN FD, ASIL-D",
    },
    # -----------------------------------------------------------------------
    # Display drivers — TFT/OLED controllers (additional)
    # -----------------------------------------------------------------------
    {
        "part": "ST7735",
        "aliases": ["ST7735", "ST7735S", "ST7735R"],
        "category": "display",
        "manufacturer": "Sitronix",
        "package": "COG",
        "datasheet": "https://www.displayfuture.com/Display/datasheet/controller/ST7735.pdf",
        "security_intel": {
            "interface": "SPI / 8080 parallel",
            "logic_voltage": "2.5V–3.3V",
            "debug_relevance": "Small TFT driver — SPI MOSI carries unencrypted framebuffer; popular on hobby boards",
        },
        "description": "262K color 132×162 TFT LCD controller, SPI/parallel",
    },
    {
        "part": "ST7789",
        "aliases": ["ST7789", "ST7789V", "ST7789VW"],
        "category": "display",
        "manufacturer": "Sitronix",
        "package": "COG",
        "datasheet": "https://www.rhydolabz.com/documents/33/ST7789.pdf",
        "security_intel": {
            "interface": "SPI / 8080-I / 8080-II parallel",
            "logic_voltage": "1.65V–3.3V",
            "debug_relevance": "240×240/320 TFT — SPI sniff captures display content; widely used in IoT dashboards",
        },
        "description": "262K color 240×320 TFT LCD controller, SPI/parallel",
    },
    {
        "part": "ILI9486",
        "aliases": ["ILI9486", "ILI9486L"],
        "category": "display",
        "manufacturer": "Ilitek",
        "package": "COF",
        "datasheet": "https://www.waveshare.com/w/upload/0/0a/ILI9486_Datasheet.pdf",
        "security_intel": {
            "interface": "SPI / 8080-I / 8080-II / 6800-I",
            "logic_voltage": "1.65V–3.3V",
            "debug_relevance": "320×480 TFT — parallel buses leak full-resolution framebuffer; SPI single-data-line tap suffices",
        },
        "description": "262K color 320×480 TFT LCD controller, SPI/parallel",
    },
    {
        "part": "ILI9488",
        "aliases": ["ILI9488"],
        "category": "display",
        "manufacturer": "Ilitek",
        "package": "COF",
        "datasheet": "https://www.hpinfotech.ro/ILI9488.pdf",
        "security_intel": {
            "interface": "SPI / DBI / DPI",
            "logic_voltage": "1.65V–3.3V",
            "debug_relevance": "320×480 TFT — DPI 24-bit RGB output exposes pixels at panel connector; trivial frame capture",
        },
        "description": "16.7M color 320×480 TFT LCD controller, SPI/RGB",
    },
    {
        "part": "SSD1331",
        "aliases": ["SSD1331"],
        "category": "display",
        "manufacturer": "Solomon Systech",
        "package": "COF",
        "datasheet": "https://www.adafruit.com/datasheets/SSD1331_1.2.pdf",
        "security_intel": {
            "interface": "SPI / 8080 / 6800",
            "logic_voltage": "2.4V–3.5V",
            "debug_relevance": "Color OLED 96×64 — SPI MOSI carries pixel stream; common on wearables",
        },
        "description": "65K color 96×64 OLED display controller, SPI",
    },
    {
        "part": "SSD1351",
        "aliases": ["SSD1351"],
        "category": "display",
        "manufacturer": "Solomon Systech",
        "package": "COF",
        "datasheet": "https://newhavendisplay.com/content/app_notes/SSD1351.pdf",
        "security_intel": {
            "interface": "SPI / 8080 / 6800",
            "logic_voltage": "2.4V–3.5V",
            "debug_relevance": "262K color 128×128 OLED — full-color framebuffer leaks over SPI",
        },
        "description": "262K color 128×128 OLED display controller, SPI",
    },
    {
        "part": "RA8875",
        "aliases": ["RA8875", "RA8875M3N"],
        "category": "display",
        "manufacturer": "RAiO",
        "package": "LQFP100",
        "datasheet": "https://cdn-shop.adafruit.com/datasheets/RA8875_DS_V19_Eng.pdf",
        "security_intel": {
            "interface": "SPI / I2C / 8080 / 6800",
            "logic_voltage": "3.3V",
            "debug_relevance": "TFT controller with GUI accelerator — exposes BTE block-transfer registers via SPI; touch panel I2C addressable",
        },
        "description": "TFT LCD controller 800×480, GPU accel, touch interface",
    },
    {
        "part": "GC9A01",
        "aliases": ["GC9A01", "GC9A01A"],
        "category": "display",
        "manufacturer": "Galaxycore",
        "package": "COG",
        "datasheet": "https://www.buydisplay.com/download/ic/GC9A01A.pdf",
        "security_intel": {
            "interface": "SPI (4-wire)",
            "logic_voltage": "1.65V–3.3V",
            "debug_relevance": "Round 240×240 TFT — SPI-only; popular in smartwatches and gauges",
        },
        "description": "262K color 240×240 round TFT controller, SPI",
    },
    {
        "part": "HX8357",
        "aliases": ["HX8357", "HX8357D"],
        "category": "display",
        "manufacturer": "Himax",
        "package": "COF",
        "datasheet": "https://cdn-shop.adafruit.com/datasheets/HX8357-D_DS_April2012.pdf",
        "security_intel": {
            "interface": "SPI / 8080 / RGB",
            "logic_voltage": "1.65V–3.3V",
            "debug_relevance": "320×480 TFT — RGB parallel bus exposes pixels; SPI also viable",
        },
        "description": "262K color 320×480 TFT controller, SPI/RGB",
    },
    {
        "part": "NT35510",
        "aliases": ["NT35510"],
        "category": "display",
        "manufacturer": "Novatek",
        "package": "COF",
        "datasheet": "https://www.melt.com.ru/docs/NT35510.pdf",
        "security_intel": {
            "interface": "SPI / 8080-II / RGB / MIPI DSI",
            "logic_voltage": "1.65V–3.3V",
            "debug_relevance": "480×800 TFT — MIPI DSI lanes need clock-recovery probe but RGB mode is plain parallel",
        },
        "description": "16.7M color 480×800 TFT controller, RGB/MIPI DSI",
    },
    {
        "part": "SSD1322",
        "aliases": ["SSD1322"],
        "category": "display",
        "manufacturer": "Solomon Systech",
        "package": "COF",
        "datasheet": "https://www.crystalfontz.com/controllers/SolomonSystech/SSD1322/",
        "security_intel": {
            "interface": "SPI / 8080 / 6800",
            "logic_voltage": "2.4V–3.5V",
            "debug_relevance": "Greyscale OLED 256×64 — SPI sniff exposes 4-bit greyscale pixels",
        },
        "description": "16-grey 256×64 OLED display controller",
    },
    # -----------------------------------------------------------------------
    # Wireless — additional ESP32 / nRF52 / SiLabs / Bouffalo
    # -----------------------------------------------------------------------
    {
        "part": "ESP32-C2",
        "aliases": ["ESP32C2", "ESP8684", "ESP32-C2-MINI"],
        "category": "mcu",
        "manufacturer": "Espressif",
        "package": "QFN32",
        "datasheet": "https://www.espressif.com/sites/default/files/documentation/esp32-c2_datasheet_en.pdf",
        "security_intel": {
            "debug_interfaces": ["JTAG"],
            "boot_mode_pins": ["GPIO8 (strapping)", "GPIO9 (strapping)"],
            "readout_protection": "Flash Encryption + Secure Boot V2 (eFuse)",
            "core": "RISC-V @ 120MHz",
            "voltage_range": "3.0V–3.6V",
        },
        "description": "RISC-V 120MHz, WiFi4+BLE5, cost-optimized 4MB Flash",
    },
    {
        "part": "ESP32-P4",
        "aliases": ["ESP32P4", "ESP32-P4-NANO"],
        "category": "mcu",
        "manufacturer": "Espressif",
        "package": "QFN64",
        "datasheet": "https://www.espressif.com/sites/default/files/documentation/esp32-p4_datasheet_en.pdf",
        "security_intel": {
            "debug_interfaces": ["JTAG", "USB-Serial-JTAG"],
            "boot_mode_pins": ["GPIO35 (strapping)", "GPIO36 (strapping)"],
            "readout_protection": "Flash Encryption + Secure Boot V2 + AES-XTS for PSRAM",
            "core": "Dual RISC-V HiFive @ 400MHz + LP RISC-V",
            "voltage_range": "3.0V–3.6V",
        },
        "description": "Dual-core RISC-V 400MHz, no radio, MIPI-CSI/DSI, AI-vision",
    },
    {
        "part": "nRF52810",
        "aliases": ["nRF52810", "NRF52810"],
        "category": "mcu",
        "manufacturer": "Nordic Semiconductor",
        "package": "QFN32",
        "datasheet": "https://infocenter.nordicsemi.com/pdf/nRF52810_PS_v1.3.pdf",
        "security_intel": {
            "debug_interfaces": ["SWD"],
            "boot_mode_pins": ["nRESET"],
            "readout_protection": "APPROTECT register (CTRL-AP lock)",
            "core": "ARM Cortex-M4 @ 64MHz",
            "voltage_range": "1.7V–3.6V",
        },
        "description": "BLE5 Cortex-M4, 192KB Flash, cost-optimized",
    },
    {
        "part": "nRF52833",
        "aliases": ["nRF52833", "NRF52833"],
        "category": "mcu",
        "manufacturer": "Nordic Semiconductor",
        "package": "QFN73",
        "datasheet": "https://infocenter.nordicsemi.com/pdf/nRF52833_PS_v1.7.pdf",
        "security_intel": {
            "debug_interfaces": ["SWD"],
            "boot_mode_pins": ["nRESET"],
            "readout_protection": "APPROTECT (CTRL-AP) + ACL flash regions",
            "core": "ARM Cortex-M4F @ 64MHz",
            "voltage_range": "1.7V–5.5V",
        },
        "description": "BLE5+802.15.4 Cortex-M4F, 512KB Flash, direction finding",
    },
    {
        "part": "EFR32MG21",
        "aliases": ["EFR32MG21", "MGM210L", "EFR32MG21A"],
        "category": "mcu",
        "manufacturer": "Silicon Labs",
        "package": "QFN32",
        "datasheet": "https://www.silabs.com/documents/public/data-sheets/efr32mg21-datasheet.pdf",
        "security_intel": {
            "debug_interfaces": ["SWD"],
            "boot_mode_pins": ["RESETn"],
            "readout_protection": "Secure Vault (Series 2): tamper, secure boot, debug lock",
            "core": "ARM Cortex-M33 @ 80MHz",
            "voltage_range": "1.71V–3.8V",
        },
        "description": "Zigbee/Thread/Matter SoC, Cortex-M33 + TrustZone, 1MB Flash",
    },
    {
        "part": "EFR32BG22",
        "aliases": ["EFR32BG22", "BGM220P", "EFR32BG22C"],
        "category": "mcu",
        "manufacturer": "Silicon Labs",
        "package": "QFN32",
        "datasheet": "https://www.silabs.com/documents/public/data-sheets/efr32bg22-datasheet.pdf",
        "security_intel": {
            "debug_interfaces": ["SWD"],
            "boot_mode_pins": ["RESETn"],
            "readout_protection": "Secure Vault Mid: secure boot RTSL, secure debug",
            "core": "ARM Cortex-M33 @ 76.8MHz",
            "voltage_range": "1.71V–3.8V",
        },
        "description": "BLE5.2 Cortex-M33 SoC, 512KB Flash, AoA/AoD direction finding",
    },
    {
        "part": "BL602",
        "aliases": ["BL602", "BL604", "BL602C20"],
        "category": "mcu",
        "manufacturer": "Bouffalo Lab",
        "package": "QFN32",
        "datasheet": "https://github.com/bouffalolab/bl_docs/raw/main/BL602_DS/en/BL602_DS_en.pdf",
        "security_intel": {
            "debug_interfaces": ["JTAG", "RV-DEBUG"],
            "boot_mode_pins": ["GPIO8 (boot strap)"],
            "readout_protection": "AES-CTR encrypted flash + Secure Boot (eFuse)",
            "core": "RISC-V RV32IMAFC @ 192MHz",
            "voltage_range": "3.0V–3.6V",
        },
        "description": "RISC-V WiFi4+BLE5 SoC, 132KB SRAM, low-cost ESP32 alternative",
    },
    {
        "part": "AT86RF215",
        "aliases": ["AT86RF215", "ATRF215"],
        "category": "rf",
        "manufacturer": "Microchip",
        "package": "QFN32",
        "datasheet": "https://ww1.microchip.com/downloads/en/DeviceDoc/AT86RF215-Data-Sheet-DS70005359G.pdf",
        "security_intel": {
            "interface": "SPI",
            "frequency": "Sub-1GHz + 2.4GHz",
            "protocol": "IEEE 802.15.4 / 802.15.4g",
            "debug_relevance": "Dual-band 802.15.4 — SPI control plane carries unencrypted PHY config; used in WiSUN networks",
        },
        "description": "Dual-band 802.15.4 transceiver, sub-GHz + 2.4GHz, SPI",
    },
    {
        "part": "ISP1807",
        "aliases": ["ISP1807", "ISP1807-LR"],
        "category": "rf",
        "manufacturer": "Insight SiP",
        "package": "Module",
        "datasheet": "https://www.insightsip.com/fichiers_insightsip/pdf/ble/ISP1807/isp_ble_DS1807.pdf",
        "security_intel": {
            "interface": "Internal nRF52840 SoC + integrated antenna",
            "frequency": "2.4GHz",
            "protocol": "BLE5 / 802.15.4 / Thread",
            "debug_relevance": "nRF52840-based module — SWD pads usually exposed under shield; APPROTECT bypass via Glitch known on some variants",
        },
        "description": "Long-range BLE5+Thread module, nRF52840-based",
    },
    {
        "part": "MGM240P",
        "aliases": ["MGM240P", "MGM240PA22VNA"],
        "category": "rf",
        "manufacturer": "Silicon Labs",
        "package": "Module",
        "datasheet": "https://www.silabs.com/documents/public/data-sheets/mgm240p-datasheet.pdf",
        "security_intel": {
            "interface": "Module (UART/SPI/I2C exposed)",
            "frequency": "2.4GHz",
            "protocol": "Matter / Zigbee / Thread / BLE",
            "debug_relevance": "EFR32MG24-based — Secure Vault High protects keys; SWD pads may still allow lifecycle inspection",
        },
        "description": "Multi-protocol Matter/Zigbee/Thread/BLE module, EFR32MG24",
    },
    # -----------------------------------------------------------------------
    # Power management — TPS6x, LTC3xxx, charge controllers, fuel gauges
    # -----------------------------------------------------------------------
    {
        "part": "TPS62130",
        "aliases": ["TPS62130", "TPS62130RGTR"],
        "category": "regulator",
        "manufacturer": "Texas Instruments",
        "package": "VQFN-16",
        "datasheet": "https://www.ti.com/lit/ds/symlink/tps62130.pdf",
        "security_intel": {
            "interface": "Static (resistor-set FB)",
            "logic_voltage": "3V–17V input",
            "debug_relevance": "3A buck — feedback resistor manipulation can fault MCU rail to bypass secure boot",
        },
        "description": "3A 17V buck converter, 0.9V–6V output, 2.5MHz",
    },
    {
        "part": "TPS61040",
        "aliases": ["TPS61040", "TPS61040DBVR"],
        "category": "regulator",
        "manufacturer": "Texas Instruments",
        "package": "SOT23-5",
        "datasheet": "https://www.ti.com/lit/ds/symlink/tps61040.pdf",
        "security_intel": {
            "interface": "Static (resistor-set FB)",
            "logic_voltage": "1.8V–6V input",
            "debug_relevance": "Boost — drives WLED/OLED rails; useful indicator of display backlight presence",
        },
        "description": "Low-power boost converter, up to 28V output, 400mA switch",
    },
    {
        "part": "TPS65186",
        "aliases": ["TPS65186", "TPS65186RSL"],
        "category": "pmic",
        "manufacturer": "Texas Instruments",
        "package": "VQFN-48",
        "datasheet": "https://www.ti.com/lit/ds/symlink/tps65186.pdf",
        "security_intel": {
            "interface": "I2C (0x68)",
            "logic_voltage": "2.7V–6V input",
            "debug_relevance": "E-paper PMIC — I2C controllable rails ±15V; signature of e-ink reader designs",
        },
        "description": "PMIC for e-paper displays, I2C, ±15V/±22V outputs",
    },
    {
        "part": "TPS22810",
        "aliases": ["TPS22810", "TPS22810DBVR"],
        "category": "regulator",
        "manufacturer": "Texas Instruments",
        "package": "SOT23-6",
        "datasheet": "https://www.ti.com/lit/ds/symlink/tps22810.pdf",
        "security_intel": {
            "interface": "GPIO ON pin",
            "logic_voltage": "1.6V–18V",
            "debug_relevance": "Load switch — enable line is a single-bit power-gate, often tied to MCU GPIO; cut to isolate rails",
        },
        "description": "18V 4A load switch with controlled rise time",
    },
    {
        "part": "LTC3406",
        "aliases": ["LTC3406", "LTC3406B"],
        "category": "regulator",
        "manufacturer": "Analog Devices",
        "package": "ThinSOT",
        "datasheet": "https://www.analog.com/media/en/technical-documentation/data-sheets/3406fc.pdf",
        "security_intel": {
            "interface": "Static (resistor-set FB)",
            "logic_voltage": "2.5V–5.5V input",
            "debug_relevance": "600mA buck — common on portable designs; FB tampering fault-injection vector",
        },
        "description": "1.5MHz 600mA synchronous buck, 2.5–5.5V input",
    },
    {
        "part": "LTC3441",
        "aliases": ["LTC3441", "LTC3441EDE"],
        "category": "regulator",
        "manufacturer": "Analog Devices",
        "package": "DFN-12",
        "datasheet": "https://www.analog.com/media/en/technical-documentation/data-sheets/3441fa.pdf",
        "security_intel": {
            "interface": "Static (resistor-set FB)",
            "logic_voltage": "2.4V–5.5V input",
            "debug_relevance": "Buck-boost — keeps rail stable across battery sweep, often gates MCU on Li-ion designs",
        },
        "description": "1.2A buck-boost DC/DC, single Li-ion to 3.3V",
    },
    {
        "part": "LTC4054",
        "aliases": ["LTC4054", "LTC4054ES5", "LTC4054-4.2"],
        "category": "battery_charger",
        "manufacturer": "Analog Devices",
        "package": "ThinSOT",
        "datasheet": "https://www.analog.com/media/en/technical-documentation/data-sheets/405442fc.pdf",
        "security_intel": {
            "interface": "Static (resistor-set Iprog) + CHRG status pin",
            "logic_voltage": "4.25V–6.5V input",
            "debug_relevance": "Single-cell Li-ion charger — CHRG pin often goes to MCU; status leaks charge state",
        },
        "description": "Standalone Li-ion linear charger, 800mA, 4.2V CV",
    },
    {
        "part": "LTC2954",
        "aliases": ["LTC2954", "LTC2954-1", "LTC2954-2"],
        "category": "pmic",
        "manufacturer": "Analog Devices",
        "package": "DFN-8",
        "datasheet": "https://www.analog.com/media/en/technical-documentation/data-sheets/2954fb.pdf",
        "security_intel": {
            "interface": "GPIO (KILL/INT/EN)",
            "logic_voltage": "2.7V–26V",
            "debug_relevance": "Pushbutton on/off — KILL pin allows MCU to force power-off; debounce timer fixed by CT cap",
        },
        "description": "Pushbutton on/off controller with µP supervisor",
    },
    {
        "part": "MP1495",
        "aliases": ["MP1495", "MP1495DJ"],
        "category": "regulator",
        "manufacturer": "Monolithic Power Systems",
        "package": "TSOT23-8",
        "datasheet": "https://www.monolithicpower.com/en/documentview/productdocument/index/version/2/document_type/Datasheet/lang/en/sku/MP1495DJ/",
        "security_intel": {
            "interface": "Static (resistor-set FB)",
            "logic_voltage": "4.5V–16V input",
            "debug_relevance": "3A buck — popular on dev boards; FB-resistor swap is classic voltage-glitch setup",
        },
        "description": "3A 16V step-down converter, 500kHz, COT control",
    },
    {
        "part": "MAX17048",
        "aliases": ["MAX17048", "MAX17048G", "MAX17049"],
        "category": "fuel_gauge",
        "manufacturer": "Analog Devices",
        "package": "TDFN-8",
        "datasheet": "https://www.analog.com/media/en/technical-documentation/data-sheets/MAX17048-MAX17049.pdf",
        "security_intel": {
            "interface": "I2C (0x36)",
            "logic_voltage": "2.5V–4.5V",
            "debug_relevance": "Battery fuel gauge — I2C read of SOC/voltage; ModelGauge data could leak usage patterns",
        },
        "description": "Single-cell Li-ion fuel gauge, ModelGauge, I2C",
    },
    {
        "part": "MCP73831",
        "aliases": ["MCP73831", "MCP73831T", "MCP73832"],
        "category": "battery_charger",
        "manufacturer": "Microchip",
        "package": "SOT23-5",
        "datasheet": "https://ww1.microchip.com/downloads/en/DeviceDoc/MCP73831-Family-Data-Sheet-DS20001984H.pdf",
        "security_intel": {
            "interface": "Static (Iprog resistor) + STAT pin",
            "logic_voltage": "3.75V–6V input",
            "debug_relevance": "Li-Po linear charger — STAT pin signals charge state; ubiquitous on hobby boards",
        },
        "description": "Single-cell Li-Ion/Li-Po linear charger, 500mA",
    },
    {
        "part": "BQ24074",
        "aliases": ["BQ24074", "BQ24074RGT"],
        "category": "battery_charger",
        "manufacturer": "Texas Instruments",
        "package": "VQFN-16",
        "datasheet": "https://www.ti.com/lit/ds/symlink/bq24074.pdf",
        "security_intel": {
            "interface": "Static config pins + status outputs",
            "logic_voltage": "4.35V–10.5V input",
            "debug_relevance": "USB-friendly Li-ion charger with power-path management — load and battery rails separable for in-system probing",
        },
        "description": "1.5A Li-Ion charger with power-path management",
    },
    {
        "part": "TPS54302",
        "aliases": ["TPS54302", "TPS54302DDC"],
        "category": "regulator",
        "manufacturer": "Texas Instruments",
        "package": "SOT-23-6",
        "datasheet": "https://www.ti.com/lit/ds/symlink/tps54302.pdf",
        "security_intel": {
            "interface": "Static (resistor-set FB)",
            "logic_voltage": "4.5V–28V input",
            "debug_relevance": "3A 28V buck — wide-input rail often supplies MCU+logic; FB tap for fault injection",
        },
        "description": "3A 28V step-down converter, EcoMode, 500kHz",
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


def _best_fuzzy_match(marking: str, threshold: float = 0.55) -> dict | None:
    """Return the best DB entry matching the marking via SequenceMatcher, or None."""
    if not marking:
        return None

    upper = marking.upper().strip()

    # Exact match first
    if upper in _LOOKUP:
        return _LOOKUP[upper]

    # Fuzzy search against all keys
    best_score = 0.0
    best_entry: dict | None = None

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


def lookup_part(marking: str) -> dict | None:
    """Public single-part lookup used by tests and CLI helpers.

    Args:
        marking: Raw marking string read from the PCB.

    Returns:
        Dict with part, category, manufacturer, package, datasheet, description
        keys — or None if no match above threshold.
    """
    return _best_fuzzy_match(marking)


def lookup_security_intel(part_number: str) -> dict | None:
    """Return the security_intel dict for a known part number, or None."""
    entry = _LOOKUP.get(part_number.upper())
    if entry:
        return entry.get("security_intel")
    return None
