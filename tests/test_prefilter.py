import pytest
from digest.prefilter import language_ok


def test_language_ok_rejects_foreign():
    rejects = [
        "Помогите , как с чего начать?",
        "När fick du ditt första jobb inom Cybersäkerhet",
        "Jakie czujniki temperatury i wilgotności polecasz",
        "Est ce que l'intelligence artificielle va nous remplacer ?",
        "Hay empresas que te contraten para aprender a programar actualmente?",
        "Das Steam Next Fest hat mich umgehauen",
        "¿Qué hace que un desafío de plataformas sea satisfactorio?",
    ]
    for title in rejects:
        assert language_ok(title) is False, f"Expected False for {title!r}"


def test_language_ok_keeps_en_vi_and_ambiguous():
    keeps = [
        "A whole city in three.js: isometric pixel-art Bielsko-Biała with live buses",
        "Công thức tiết kiệm của ông bà cha mẹ thời xưa",
        "Anyone tried this yet?",
        "Llama.cpp",
        "",
    ]
    for title in keeps:
        assert language_ok(title) is True, f"Expected True for {title!r}"
