import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
WORK: pathlib.Path = ROOT / "work"
DIGESTS: pathlib.Path = ROOT / "digests"

MIN_SCORE: int = 7
MAX_PER_SUB: int = 15
TOP_N: int = 10
TOP_MIN_SCORE: int = 9
FEWSHOT_N: int = 15
SCREEN_TOP_K: int = 300

FEEDS: list[tuple[str, list[str]]] = [
    ("LocalLLaMA", ["LocalLLaMA"]),
    ("ClaudeCode", ["ClaudeCode"]),
    ("ClaudeAI", ["ClaudeAI"]),
    ("local-ai", ["DeepSeek", "Qwen_AI"]),
    (
        "ai-agents",
        [
            "GeminiAI",
            "google_antigravity",
            "CommandCode",
            "opencodeCLI",
            "PiCodingAgent",
            "claudeskills",
            "claude",
            "Claudeopus",
        ],
    ),
    (
        "hardware",
        [
            "embedded",
            "esp32",
            "IOT",
            "FPGA",
            "PCB",
            "KiCad",
            "CheapYellowDisplay",
            "PrintedCircuitBoard",
            "electronics",
        ],
    ),
    (
        "game-3d",
        [
            "blender",
            "IndieDev",
            "TopologyAI",
            "aigamedev",
            "mocap",
            "threejs",
            "SoloDevelopment",
            "DestroyMyGame",
        ],
    ),
    ("repos", ["SideProject", "BestGitHubRepos", "coolgithubprojects"]),
    (
        "ai-media",
        [
            "StableDiffusion",
            "AI_UGC_Marketing",
            "YT_Faceless",
            "DigitalProductSellers",
        ],
    ),
    (
        "career",
        [
            "softwareengineer",
            "cscareerquestions",
            "EngineeringResumes",
        ],
    ),
    ("security", ["netsecstudents", "SecurityCareerAdvice", "AskNetsec"]),
    ("learning", ["compsci", "Learning", "learnpython"]),
]
