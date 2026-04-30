"""Known-device registry for popular hardware RE targets.

Maps product names to FCC IDs, iFixit guide IDs, and hardware revisions.
When fcc.report search is unavailable, the registry provides instant local
lookup with richer metadata than any external API.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class HardwareRevision:
    """A specific hardware revision of a device model."""

    name: str
    model_number: str
    fcc_id: str
    ifixit_guide: int | None = None
    year: int | None = None
    codename: str = ""
    soc: str = ""
    ram: str = ""
    storage: str = ""
    notes: str = ""


@dataclass
class DeviceFamily:
    """A product line with multiple hardware revisions."""

    name: str
    manufacturer: str
    category: str = ""
    revisions: list[HardwareRevision] = field(default_factory=list)


# ── Xbox One ─────────────────────────────────────────────────────────

_XBOX_ONE = DeviceFamily(
    name="Xbox One",
    manufacturer="Microsoft",
    category="game_console",
    revisions=[
        HardwareRevision(
            "Xbox One (Original)", "1540", "C3K1520",
            ifixit_guide=19718, year=2013, codename="Durango",
            soc="AMD Jaguar 8-core + GCN 853MHz", ram="8GB DDR3",
            storage="500GB HDD", notes="External PSU, Kinect port, HDMI-in passthrough",
        ),
        HardwareRevision(
            "Xbox One (Revised, no Kinect)", "1540B", "C3K1520",
            year=2015, codename="Durango",
            soc="AMD Jaguar 8-core + GCN 853MHz", ram="8GB DDR3",
            storage="1TB HDD", notes="Removed Kinect port, matte finish, 1TB default",
        ),
        HardwareRevision(
            "Xbox One S", "1681", "C3K1681",
            ifixit_guide=65572, year=2016,
            soc="AMD Jaguar 8-core + GCN (16nm shrink)", ram="8GB DDR3",
            storage="500GB/1TB/2TB HDD", notes="40% smaller, internal PSU, 4K Blu-ray, HDR, IR blaster",
        ),
        HardwareRevision(
            "Xbox One S (Revised)", "1681B", "C3K1681",
            year=2017,
            soc="AMD Jaguar 8-core + GCN (16nm)", ram="8GB DDR3",
            storage="500GB/1TB HDD", notes="Minor board revision, no Kinect adapter port",
        ),
        HardwareRevision(
            "Xbox One S All-Digital", "1832", "C3K1832",
            year=2019,
            soc="AMD Jaguar 8-core + GCN (16nm)", ram="8GB DDR3",
            storage="1TB HDD", notes="No optical drive, lower MSRP",
        ),
        HardwareRevision(
            "Xbox One X", "1787", "C3K1698",
            ifixit_guide=99609, year=2017, codename="Scorpio",
            soc="AMD Jaguar 8-core + GCN 40CU 1172MHz", ram="12GB GDDR5",
            storage="1TB HDD", notes="6 TFLOPS, vapor chamber cooling, 4K gaming, HDMI 2.0b",
        ),
        HardwareRevision(
            "Xbox One X (Project Scorpio Edition)", "1787", "C3K1698",
            ifixit_guide=99609, year=2017, codename="Scorpio",
            soc="AMD Jaguar 8-core + GCN 40CU 1172MHz", ram="12GB GDDR5",
            storage="1TB HDD", notes="Limited edition, same hardware as standard One X, gradient finish",
        ),
    ],
)


# ── Xbox Series ──────────────────────────────────────────────────────

_XBOX_SERIES = DeviceFamily(
    name="Xbox Series",
    manufacturer="Microsoft",
    category="game_console",
    revisions=[
        HardwareRevision(
            "Xbox Series X", "1882", "C3K1882",
            ifixit_guide=139266, year=2020, codename="Anaconda",
            soc="AMD Zen 2 8-core + RDNA 2 52CU", ram="16GB GDDR6",
            storage="1TB NVMe SSD", notes="12 TFLOPS, split motherboard, vapor chamber, 4K120/8K",
        ),
        HardwareRevision(
            "Xbox Series S", "1883", "C3K1883",
            ifixit_guide=139298, year=2020, codename="Lockhart",
            soc="AMD Zen 2 8-core + RDNA 2 20CU", ram="10GB GDDR6",
            storage="512GB NVMe SSD", notes="4 TFLOPS, digital only, compact form factor",
        ),
        HardwareRevision(
            "Xbox Series S (1TB)", "1883B", "C3K1883",
            year=2023,
            soc="AMD Zen 2 8-core + RDNA 2 20CU", ram="10GB GDDR6",
            storage="1TB NVMe SSD", notes="Carbon Black edition, doubled storage",
        ),
    ],
)


# ── PlayStation 5 ────────────────────────────────────────────────────

_PS5 = DeviceFamily(
    name="PlayStation 5",
    manufacturer="Sony",
    category="game_console",
    revisions=[
        HardwareRevision(
            "PS5 (Launch, disc)", "CFI-1015A", "AK8CFI-1015A",
            ifixit_guide=139292, year=2020, codename="Oberon",
            soc="AMD Zen 2 8-core + RDNA 2 36CU", ram="16GB GDDR6",
            storage="825GB NVMe SSD", notes="Launch model, 350W PSU, large heatsink",
        ),
        HardwareRevision(
            "PS5 Digital (Launch)", "CFI-1015B", "AK8CFI-1015B",
            year=2020, codename="Oberon",
            soc="AMD Zen 2 8-core + RDNA 2 36CU", ram="16GB GDDR6",
            storage="825GB NVMe SSD", notes="No disc drive, otherwise identical to CFI-1015A",
        ),
        HardwareRevision(
            "PS5 (Rev 2, disc)", "CFI-1115A", "AK8CFI-1115A",
            year=2021, codename="Oberon",
            soc="AMD Zen 2 8-core + RDNA 2 36CU", ram="16GB GDDR6",
            storage="825GB NVMe SSD", notes="300g lighter, smaller heatsink, new screw for SSD slot",
        ),
        HardwareRevision(
            "PS5 Digital (Rev 2)", "CFI-1115B", "AK8CFI-1115B",
            year=2021,
            soc="AMD Zen 2 8-core + RDNA 2 36CU", ram="16GB GDDR6",
            storage="825GB NVMe SSD", notes="Lighter digital variant",
        ),
        HardwareRevision(
            "PS5 (Rev 3, disc)", "CFI-1215A", "AK8CFI-1215A",
            year=2022, codename="Oberon Plus",
            soc="AMD Zen 2 8-core + RDNA 2 (6nm shrink)", ram="16GB GDDR6",
            storage="825GB NVMe SSD", notes="6nm die shrink, smaller board, liquid metal TIM, 600g lighter than launch",
        ),
        HardwareRevision(
            "PS5 Digital (Rev 3)", "CFI-1215B", "AK8CFI-1215B",
            year=2022, codename="Oberon Plus",
            soc="AMD Zen 2 8-core + RDNA 2 (6nm)", ram="16GB GDDR6",
            storage="825GB NVMe SSD", notes="6nm digital variant",
        ),
        HardwareRevision(
            "PS5 Slim (disc)", "CFI-2015", "AK8CFI-2015",
            year=2023,
            soc="AMD Zen 2 8-core + RDNA 2 (6nm)", ram="16GB GDDR6",
            storage="1TB NVMe SSD", notes="30% smaller, detachable disc drive, 2 USB-C ports",
        ),
        HardwareRevision(
            "PS5 Slim Digital", "CFI-2015B", "AK8CFI-2015",
            year=2023,
            soc="AMD Zen 2 8-core + RDNA 2 (6nm)", ram="16GB GDDR6",
            storage="1TB NVMe SSD", notes="Slim without disc drive, attachable later",
        ),
        HardwareRevision(
            "PS5 Pro", "CFI-7015", "AK8CFI-7015",
            year=2024, codename="Trinity",
            soc="AMD Zen 2 8-core + RDNA 2++ 60CU", ram="16GB GDDR6 (28GT/s)",
            storage="2TB NVMe SSD", notes="16.7 TFLOPS, AI-accelerated upscaling (PSSR), 2x ray tracing, WiFi 7",
        ),
    ],
)


# ── Nintendo Switch ──────────────────────────────────────────────────

_SWITCH = DeviceFamily(
    name="Nintendo Switch",
    manufacturer="Nintendo",
    category="game_console",
    revisions=[
        HardwareRevision(
            "Switch (Original)", "HAC-001", "BKEHAC001",
            ifixit_guide=78263, year=2017, codename="Erista (T210)",
            soc="NVIDIA Tegra X1 (20nm)", ram="4GB LPDDR4",
            storage="32GB eMMC", notes="First gen, exploitable bootrom (Fusée Gelée CVE-2018-6242)",
        ),
        HardwareRevision(
            "Switch V2 (Mariko)", "HAC-001(-01)", "BKEHAC001",
            year=2019, codename="Mariko (T214)",
            soc="NVIDIA Tegra X1+ (16nm)", ram="4GB LPDDR4",
            storage="32GB eMMC", notes="Red box packaging, 40% better battery, patched bootrom",
        ),
        HardwareRevision(
            "Switch Lite", "HDH-001", "BKEHDH001",
            ifixit_guide=126498, year=2019, codename="Mariko Lite",
            soc="NVIDIA Tegra X1+ (16nm)", ram="4GB LPDDR4",
            storage="32GB eMMC", notes="Handheld only, no docking, no detachable Joy-Cons, 5.5\" LCD",
        ),
        HardwareRevision(
            "Switch OLED", "HEG-001", "BKEHEG001",
            ifixit_guide=144545, year=2021, codename="Aula (T214)",
            soc="NVIDIA Tegra X1+ (16nm)", ram="4GB LPDDR4",
            storage="64GB eMMC", notes="7\" OLED display, wide adjustable kickstand, LAN port in dock",
        ),
    ],
)


# ── Steam Deck ───────────────────────────────────────────────────────

_STEAM_DECK = DeviceFamily(
    name="Steam Deck",
    manufacturer="Valve",
    category="game_console",
    revisions=[
        HardwareRevision(
            "Steam Deck (LCD)", "1010", "2ADZL1010",
            ifixit_guide=148893, year=2022, codename="Jupiter",
            soc="AMD Van Gogh (Zen 2 + RDNA 2, 4C/8T)", ram="16GB LPDDR5",
            storage="64GB eMMC / 256GB NVMe / 512GB NVMe", notes="7\" LCD, 40Wh battery, trackpads + gyro",
        ),
        HardwareRevision(
            "Steam Deck OLED", "1030", "2ADZL1030",
            ifixit_guide=154676, year=2023, codename="Galileo",
            soc="AMD Sephiroth (Zen 2 + RDNA 2, 6nm shrink)", ram="16GB LPDDR5-6400",
            storage="512GB / 1TB NVMe", notes="7.4\" OLED 90Hz, 50Wh battery, WiFi 6E, Bluetooth 5.3",
        ),
    ],
)


# ── Raspberry Pi ─────────────────────────────────────────────────────

_RASPBERRY_PI = DeviceFamily(
    name="Raspberry Pi",
    manufacturer="Raspberry Pi Foundation",
    category="sbc",
    revisions=[
        HardwareRevision(
            "Raspberry Pi 5", "RPI5B", "2ABCB-RPI5B",
            year=2023,
            soc="BCM2712 (Cortex-A76 4-core 2.4GHz)", ram="4/8GB LPDDR4X",
            storage="microSD / NVMe via HAT", notes="PCIe 2.0 x1, dual 4K HDMI, USB 3.0, RP1 southbridge",
        ),
        HardwareRevision(
            "Raspberry Pi 4B (Rev 1.1)", "RPI4B", "2ABCB-RPI4B",
            year=2019,
            soc="BCM2711 (Cortex-A72 4-core 1.5GHz)", ram="1/2/4GB LPDDR4",
            storage="microSD", notes="Initial revision, USB-C charging issue (CC resistors)",
        ),
        HardwareRevision(
            "Raspberry Pi 4B (Rev 1.2)", "RPI4B-1.2", "2ABCB-RPI4B",
            year=2020,
            soc="BCM2711 (Cortex-A72 4-core 1.8GHz)", ram="2/4/8GB LPDDR4",
            storage="microSD", notes="Fixed USB-C, added 8GB option, higher clock",
        ),
        HardwareRevision(
            "Raspberry Pi 400", "RPI400", "2ABCB-RPI400",
            year=2020,
            soc="BCM2711 (Cortex-A72 4-core 1.8GHz)", ram="4GB LPDDR4",
            storage="microSD", notes="Keyboard form factor, passive cooling, GPIO header on back",
        ),
        HardwareRevision(
            "Raspberry Pi Zero 2 W", "RPIZ2W", "2ABCB-RPIZ2",
            year=2021,
            soc="BCM2710A1 (Cortex-A53 4-core 1GHz)", ram="512MB LPDDR2",
            storage="microSD", notes="Quad-core upgrade from original Zero, WiFi/BT, same form factor",
        ),
    ],
)


# ── Ubiquiti ─────────────────────────────────────────────────────────

_UBIQUITI = DeviceFamily(
    name="Ubiquiti UniFi",
    manufacturer="Ubiquiti",
    category="networking",
    revisions=[
        HardwareRevision(
            "UniFi AP AC Pro", "UAP-AC-PRO", "SWX-UAPACPRO",
            year=2015,
            soc="Qualcomm Atheros QCA9563 + QCA9880", ram="128MB DDR2",
            notes="Dual-band 802.11ac 3x3 MIMO, PoE 802.3af/at",
        ),
        HardwareRevision(
            "UniFi Dream Machine", "UDM", "SWX-UDM",
            year=2019,
            soc="Annapurna Labs AL-324 (Cortex-A57 4-core)", ram="2GB DDR4",
            storage="16GB eMMC", notes="All-in-one router/switch/AP/controller",
        ),
        HardwareRevision(
            "UniFi Dream Machine Pro", "UDM-PRO", "SWX-UDMPRO",
            year=2020,
            soc="Annapurna Labs AL-324 (Cortex-A57 4-core)", ram="4GB DDR4",
            storage="16GB eMMC + 3.5\" HDD bay", notes="1U rackmount, 10G SFP+, IDS/IPS, Protect NVR",
        ),
        HardwareRevision(
            "UniFi Dream Machine SE", "UDM-SE", "SWX-UDMSE",
            year=2022,
            soc="Annapurna Labs AL-324", ram="4GB DDR4",
            storage="128GB SSD", notes="Built-in PoE switch (8 ports), 2.5G WAN, upgraded IDS/IPS",
        ),
    ],
)


# ── Ring / Amazon ────────────────────────────────────────────────────

_RING = DeviceFamily(
    name="Ring Doorbell",
    manufacturer="Amazon/Ring",
    category="iot",
    revisions=[
        HardwareRevision(
            "Ring Video Doorbell (Gen 1)", "?"  , "2AEUP-BAH01",
            year=2018,
            soc="Ambarella S2L", ram="256MB",
            notes="1080p, 802.11b/g/n, battery or hardwired",
        ),
        HardwareRevision(
            "Ring Video Doorbell 2", "5UM5E5", "2AEUP-0DG00I",
            year=2019,
            notes="Removable battery, 1080p, improved motion detection",
        ),
        HardwareRevision(
            "Ring Video Doorbell Pro 2", "5AT3T5", "2AEUP-0FMHM5",
            year=2021,
            notes="Hardwired, 3D motion detection, bird's eye view, 1536p head-to-toe",
        ),
    ],
)


# ── Cisco ASA ───────────────────────────────────────────────────────

_CISCO_ASA = DeviceFamily(
    name="Cisco ASA",
    manufacturer="Cisco",
    category="firewall",
    revisions=[
        HardwareRevision(
            "ASA 5505 (Base)", "ASA5505-BUN-K9", "LDK102057",
            year=2006,
            soc="AMD Geode LX800 500MHz", ram="256MB DDR",
            storage="64MB CompactFlash",
            notes="8-port FE, 10K users, EXTRABACON target (CVE-2016-6366, Shadow Brokers/NSA)",
        ),
        HardwareRevision(
            "ASA 5505 (Security Plus)", "ASA5505-SEC-BUN-K9", "LDK102057",
            year=2006,
            soc="AMD Geode LX800 500MHz", ram="256MB DDR",
            storage="64MB CompactFlash",
            notes="Trunking, failover, DMZ, 25K users, same hardware as Base license",
        ),
        HardwareRevision(
            "ASA 5506-X", "ASA5506-K9", "N/A-wired",
            year=2015, codename="Firepower",
            soc="Intel Atom C2508 (Rangeley, 4-core 1.25GHz, FCBGA-1283)", ram="4GB DDR3 ECC",
            storage="8GB eUSB + 50GB mSATA SSD",
            notes="8-port GbE, FirePOWER IPS, Thrangrycat (CVE-2019-1649), ArcaneDoor APT, "
                  "CISA ED 25-03, Intel AVR54 clock bug, Xilinx Spartan-6 Trust Anchor FPGA, "
                  "wired-only (no FCC ID), EOL Aug 2026, board revs V02-V06",
        ),
        HardwareRevision(
            "ASA 5506W-X", "ASA5506W-A-K9", "LDKASA-AP702",
            year=2015, codename="Firepower",
            soc="Intel Atom C2508 (Rangeley, 4-core 1.25GHz, FCBGA-1283)", ram="4GB DDR3 ECC",
            storage="8GB eUSB + 50GB mSATA SSD",
            notes="Same as 5506-X + 802.11ac WAP (ASA-AP702), FCC ID is for WiFi module only",
        ),
        HardwareRevision(
            "ASA 5508-X", "ASA5508-K9", "N/A-wired",
            year=2015, codename="Firepower",
            soc="Intel Atom C2518 (Rangeley, 4-core 1.7GHz, FCBGA-1283)", ram="8GB DDR3 ECC",
            storage="8GB eUSB + 50GB mSATA SSD",
            notes="8-port GbE, higher throughput, FirePOWER IPS, same CVEs + Trust Anchor as 5506-X",
        ),
        HardwareRevision(
            "ASA 5510", "ASA5510-BUN-K9", "LDK102060",
            year=2006,
            soc="Intel Celeron M 1.6GHz", ram="256MB DDR",
            storage="64MB CompactFlash",
            notes="5-port FE + 1 GbE, 130K connections, DMZ, CVE-2016-1287 IKE overflow (CVSS 10.0)",
        ),
        HardwareRevision(
            "ASA 5515-X", "ASA5515-K9", "LDK102068",
            year=2012,
            soc="Intel Core i5 (Sandy Bridge)", ram="8GB DDR3",
            storage="8GB SSD",
            notes="6-port GbE, 250K connections, IPS module slot, predecessor to 5506-X",
        ),
        HardwareRevision(
            "ASA 5516-X", "ASA5516-FPWR-K9", "LDK102074",
            year=2016, codename="Firepower",
            soc="Intel Atom C2518 (Rangeley, 4-core 1.7GHz)", ram="8GB DDR3",
            storage="8GB mSATA SSD",
            notes="8-port GbE, FirePOWER bundled, HA failover, successor to 5515-X",
        ),
    ],
)


# ── Cisco Catalyst ──────────────────────────────────────────────────

_CISCO_CATALYST = DeviceFamily(
    name="Cisco Catalyst",
    manufacturer="Cisco",
    category="switch",
    revisions=[
        HardwareRevision(
            "Catalyst 2960-X (24 port)", "WS-C2960X-24TS-L", "LDK102071",
            year=2013,
            soc="Marvell Prestera 98DX3236 (ARM)", ram="512MB DDR3",
            storage="64MB flash",
            notes="Most-deployed enterprise switch ever, 24-port GbE + 4 SFP, LAN Base",
        ),
        HardwareRevision(
            "Catalyst 2960-X (48 port)", "WS-C2960X-48TS-L", "LDK102071",
            year=2013,
            soc="Marvell Prestera 98DX3236 (ARM)", ram="512MB DDR3",
            storage="64MB flash",
            notes="48-port GbE + 4 SFP, FlexStack-Plus stacking, LAN Base",
        ),
        HardwareRevision(
            "Catalyst 3560-X (24 port)", "WS-C3560X-24T-S", "LDK102065",
            year=2011,
            soc="Memory controller ASIC + Memory forwarding ASIC", ram="256MB DDR2",
            storage="64MB flash",
            notes="24-port GbE, IP Base/Services, Layer 3, network module slot",
        ),
    ],
)


# ── Master registry ──────────────────────────────────────────────────

DEVICE_FAMILIES: list[DeviceFamily] = [
    _XBOX_ONE,
    _XBOX_SERIES,
    _PS5,
    _SWITCH,
    _STEAM_DECK,
    _RASPBERRY_PI,
    _UBIQUITI,
    _RING,
    _CISCO_ASA,
    _CISCO_CATALYST,
]


def search_registry(query: str) -> list[tuple[DeviceFamily, list[HardwareRevision]]]:
    """Search the device registry by keyword. Case-insensitive partial match.

    Returns a list of (family, matching_revisions) tuples. If the query
    matches the family name, all revisions are returned. If it matches a
    specific revision name, codename, or model number, only those revisions
    are included.
    """
    q = query.lower().strip()
    results: list[tuple[DeviceFamily, list[HardwareRevision]]] = []

    for family in DEVICE_FAMILIES:
        if q in family.name.lower() or q in family.manufacturer.lower():
            results.append((family, list(family.revisions)))
            continue

        matching = [
            r for r in family.revisions
            if q in r.name.lower()
            or q in r.model_number.lower()
            or q in r.fcc_id.lower()
            or (r.codename and q in r.codename.lower())
        ]
        if matching:
            results.append((family, matching))

    return results


def get_family(name: str) -> DeviceFamily | None:
    """Get a device family by exact name (case-insensitive)."""
    for f in DEVICE_FAMILIES:
        if f.name.lower() == name.lower():
            return f
    return None


def get_revision_by_fcc_id(fcc_id: str) -> tuple[DeviceFamily, HardwareRevision] | None:
    """Look up a specific revision by FCC ID."""
    fcc_upper = fcc_id.upper()
    for family in DEVICE_FAMILIES:
        for rev in family.revisions:
            if rev.fcc_id.upper() == fcc_upper:
                return (family, rev)
    return None


def format_search_results(results: list[tuple[DeviceFamily, list[HardwareRevision]]]) -> str:
    """Format search results for CLI display."""
    lines: list[str] = []
    for family, revisions in results:
        lines.append(f"\n  {family.name} ({family.manufacturer})")
        lines.append(f"  {'─' * 50}")
        for i, rev in enumerate(revisions, 1):
            guide = f"  iFixit #{rev.ifixit_guide}" if rev.ifixit_guide else ""
            codename_str = f"  [{rev.codename}]" if rev.codename else ""
            lines.append(
                f"    {i}. {rev.name}  ({rev.year or '?'})"
            )
            lines.append(
                f"       Model: {rev.model_number}  FCC: {rev.fcc_id}{guide}{codename_str}"
            )
            if rev.soc:
                lines.append(f"       SoC: {rev.soc}")
            if rev.ram:
                lines.append(f"       RAM: {rev.ram}  Storage: {rev.storage or 'N/A'}")
            if rev.notes:
                lines.append(f"       {rev.notes}")
    return "\n".join(lines)
