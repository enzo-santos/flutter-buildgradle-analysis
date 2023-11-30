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


NEW_LINE_GRAMMAR = petitparser.character.of("\n") & petitparser.character.of(" ").star()

T = typing.TypeVar("T")


def constant(call: typing.Callable[[], T]) -> T:
    return call()


@constant
def COMMENT_GRAMMAR():
    return (
        petitparser.character.of(" ").star()
        & petitparser.string.of("//")
        & petitparser.character.none_of("\n").star()
        & petitparser.character.of("\n")
    )


@constant
def OLD_PLUGINS_DECLARATION_GRAMMAR():
    """
    Parses the old `plugins` declaration.

    The old `plugins` declaration can appear on *build.gradle* as

    ```groovy
    plugins {
        id "com.android.application"
        id 'com.google.gms.google-services'
        id "kotlin-android"
        id "dev.flutter.flutter-gradle-plugin"
    }
    ```
    """
    plugin_declaration_grammar = (
        petitparser.string.of("id ")
        & petitparser.character.any_of("'\"")
        & petitparser.character.none_of("'\"").plus()
        & petitparser.character.any_of("'\"")
    )

    return (
        petitparser.string.of("plugins {")
        & NEW_LINE_GRAMMAR
        & (plugin_declaration_grammar & NEW_LINE_GRAMMAR).plus()
        & petitparser.string.of("}\n")
    )


@typing.overload
def build_flutter_property_grammar(name: str, key: str):
    ...


@typing.overload
def build_flutter_property_grammar(name: str, key: str, label: str, description: str):
    ...


def build_flutter_property_grammar(name: str, key: str, *args: str):
    if args:
        label, description = args
        body_grammar = (
            petitparser.string.of("throw")
            & petitparser.string.of(" new").optional()
            & petitparser.string.of(" ")
            & (
                petitparser.string.of("GradleException")
                | petitparser.string.of("FileNotFoundException")
            )
            & petitparser.string.of(
                f'("{label} not found. Define {description.format(key)} in the local.properties file.")'
            )
        )
    else:
        body_grammar = (
            petitparser.string.of(f"{name} = ")
            & petitparser.character.any_of("'\"")
            & petitparser.character.none_of("'\"").plus()
            & petitparser.character.any_of("'\"")
        )

    return (
        petitparser.string.of(f"def {name} = localProperties.getProperty('{key}')")
        & NEW_LINE_GRAMMAR
        & petitparser.string.of(f"if ({name} == null) {{")
        & NEW_LINE_GRAMMAR
        & body_grammar
        & NEW_LINE_GRAMMAR
        & petitparser.string.of("}\n")
    )


def build_properties_file_load_grammar(variable: str, file_variable: str, name: str):
    return (
        petitparser.string.of(f"def {variable} = new Properties()")
        & NEW_LINE_GRAMMAR
        & petitparser.string.of(f"def {file_variable} = rootProject.file('{name}')")
        & NEW_LINE_GRAMMAR
        & petitparser.string.of(f"if ({file_variable}.exists()) {{")
        & NEW_LINE_GRAMMAR
        & petitparser.string.of(f"{file_variable}.")
        & (
            petitparser.string.of("withReader('UTF-8') { reader ->")
            | petitparser.string.of("withInputStream { stream ->")
        )
        & NEW_LINE_GRAMMAR
        & petitparser.string.of(f"{variable}.load(")
        & (petitparser.string.of("reader") | petitparser.string.of("stream"))
        & petitparser.string.of(")")
        & NEW_LINE_GRAMMAR
        & petitparser.string.of("}\n}\n")
    )


class Section(typing.NamedTuple):
    grammar: petitparser.parser.Parser[str]
    is_persistent: bool
    is_required: bool


def main() -> None:
    # download_repos()

    for fpath in map(os.path.normpath, glob.glob("build/files/*.build.gradle")):
        sections: dict[str, Section] = {
            "comment": Section(
                grammar=COMMENT_GRAMMAR,
                is_persistent=True,
                is_required=False,
            ),
            "newline": Section(
                grammar=petitparser.character.of("\n").plus(),
                is_persistent=True,
                is_required=False,
            ),
            "old_plugins": Section(
                grammar=OLD_PLUGINS_DECLARATION_GRAMMAR,
                is_persistent=False,
                is_required=False,
            ),
            "localProperties": Section(
                grammar=build_properties_file_load_grammar(
                    "localProperties", "localPropertiesFile", "local.properties"
                ),
                is_persistent=False,
                is_required=True,
            ),
            "keystoreProperties": Section(
                grammar=build_properties_file_load_grammar(
                    "keystoreProperties", "keystorePropertiesFile", "key.properties"
                ),
                is_persistent=False,
                is_required=False,
            ),
            "flutterRoot": Section(
                grammar=build_flutter_property_grammar(
                    "flutterRoot",
                    "flutter.sdk",
                    "Flutter SDK",
                    "location with {}",
                ),
                is_persistent=False,
                is_required=True,
            ),
        }
        with open(fpath, encoding="utf-8") as f:
            text = f.read()

            sections_found: list[str] = []
            while not sections_found or not all(
                (section := sections[section_id]).is_persistent
                or not section.is_required
                for section_id in (set(sections.keys()) - set(sections_found))
            ):
                found = False
                for section_id, section in sections.items():
                    result = section.grammar.token().parse(text)
                    if not result.is_success:
                        # print(fpath, section_id, result.message, f"{text[:30]!r}")
                        continue
                    token = result.value
                    text = text[token.stop :]
                    sections_found.append(section_id)
                    found = True
                    break

                if not found:
                    # print(fpath)
                    break






            print(fpath, sections_found)


if __name__ == "__main__":
    main()
