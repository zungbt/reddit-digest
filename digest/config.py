import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
WORK: pathlib.Path = ROOT / "work"
DIGESTS: pathlib.Path = ROOT / "digests"

FEEDS: list[tuple[str, list[str]]] = [
    ("LocalLLaMA", ["LocalLLaMA"]),
    ("LocalLLM", ["LocalLLM"]),
    ("ClaudeCode", ["ClaudeCode"]),
    ("ClaudeAI", ["ClaudeAI"]),
    ("local-ai", ["DeepSeek", "Qwen_AI", "unsloth"]),
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
