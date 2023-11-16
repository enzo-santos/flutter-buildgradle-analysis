import re
import os
import glob
import shutil
import typing
import logging

import requests
import petitparser
import marko.block
import marko.inline
import marko.parser


def download_file_from_url(url: str, path: str, force: bool = False) -> bool:
    if not force and os.path.exists(path):
        return True

    response = requests.get(url, stream=True)
    if not response.ok:
        return False

    try:
        os.makedirs(os.path.dirname(path))
    except FileExistsError:
        pass

    with open(path, "wb+") as f:
        response.raw.decode_content = True
        shutil.copyfileobj(response.raw, f)

    return True


def decode_links(path: str) -> typing.Iterator[str]:
    parser = marko.parser.Parser()
    with open(path, encoding="utf-8") as f:
        document = parser.parse(f.read())

    current_section_name: str | None = None
    sections: set[str] = set()
    for node in document.children:
        match node:
            case marko.block.Heading():
                (text_node,) = node.children
                assert isinstance(text_node, marko.inline.RawText)

                title = text_node.children
                current_section_name = title

            case marko.block.List():
                if current_section_name == "Contents":
                    for li_node in node.children:
                        assert isinstance(li_node, marko.block.ListItem)
                        (p_node,) = li_node.children

                        assert isinstance(p_node, marko.block.Paragraph)
                        (a_node,) = p_node.children

                        assert isinstance(a_node, marko.inline.Link)
                        (text_node,) = typing.cast(list, a_node.children)

                        assert isinstance(text_node, marko.inline.RawText)
                        section_title = text_node.children
                        sections.add(section_title.lower())

                elif current_section_name:
                    assert (
                        current_section_name.lower() in sections
                    ), f"Invalid section: {current_section_name}"
                    for li_node in node.children:
                        assert isinstance(li_node, marko.block.ListItem)
                        (p_node,) = li_node.children

                        assert isinstance(p_node, marko.block.Paragraph)
                        link_node, *_ = p_node.children

                        assert isinstance(link_node, marko.inline.Link)
                        yield link_node.dest


def download_repos() -> None:
    source_path = "build/source_readme.md"
    source_url = "https://raw.githubusercontent.com/tortuvshin/open-source-flutter-apps/master/README.md"
    if not download_file_from_url(source_url, source_path):
        raise ValueError()

    monorepos: typing.Final[dict[tuple[str, str], str]] = {
        ("csuka1219", "Flutter_League"): "flutter_league",
        ("piggyvault", "piggyvault"): "src/Mobile/piggy_flutter",
        ("openfoodfacts", "smooth-app"): "packages/smooth_app",
        ("VarunS2002", "Flutter-Sudoku"): "sudoku",
        ("jerald-jacob", "Flutter-Apps"): "Hangman",
        ("roughike", "inKino"): "mobile",
        ("Big-Fig", "Fediverse.app"): "packages/fedi_app",
        ("Widle-Studio", "Grocery-App"): "f_groceries",
        ("woosignal", "flutter-woocommerce-app"): "LabelStoreMax",
        ("memspace", "zefyr"): "packages/zefyr/example",
        ("immich-app", "immich"): "mobile",
    }

    for link in decode_links(source_path):
        _, _, _, user_name, repo_name, *_ = link.split("/", 5)
        monorepo_path: str = monorepos.get((user_name, repo_name), "")
        if monorepo_path:
            monorepo_path = f"{monorepo_path}/"

        for branch_name in ("main", "master", "develop"):
            buildgradle_url = f"https://raw.githubusercontent.com/{user_name}/{repo_name}/{branch_name}/{monorepo_path}android/app/build.gradle"
            buildgradle_path = f"build/files/{user_name}_{repo_name}.build.gradle"
            if download_file_from_url(buildgradle_url, buildgradle_path):
                break

        else:
            logging.debug(f"build.gradle not found for {link}")


def build_local_properties_definition_grammar():
    grammar = petitparser.string.of(
        "def localProperties = new Properties()\ndef localPropertiesFile = rootProject.file('local.properties')\nif (localPropertiesFile.exists()) {\n  "
    )
    grammar = grammar & petitparser.string.of("  ").optional()
    grammar = grammar & petitparser.string.of("localPropertiesFile.")
    grammar = grammar & (
        petitparser.string.of("withReader('UTF-8') { reader ->\n")
        | petitparser.string.of("withInputStream { stream ->\n")
    )
    grammar = grammar & petitparser.string.of("    ").optional()
    grammar = grammar & petitparser.string.of("    ").optional()
    grammar = grammar & petitparser.string.of("localProperties.load(")
    grammar = grammar & (
        petitparser.string.of("reader") | petitparser.string.of("stream")
    )
    grammar = grammar & petitparser.string.of(")\n  ")
    grammar = grammar & petitparser.string.of("  ").optional()
    grammar = grammar & petitparser.string.of("}\n}")
    return grammar


def main() -> None:
    download_repos()

    comment_regexp = re.compile(r"^\s*//")
    for fpath in glob.glob("build/files/*.build.gradle"):
        grammars = [build_local_properties_definition_grammar()]
        with open(fpath, encoding="utf-8") as f:
            text = f.read()
            grammar = grammars[0].token()
            result = grammar.parse(text)
            if result.is_success:
                token = result.value
                print("matched:", text[token.start : token.stop])
                continue
            return

        print(fpath)


if __name__ == "__main__":
    main()
