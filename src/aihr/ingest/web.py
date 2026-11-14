"""Вакансия по ссылке (D58): страница hh.ru, сайта работодателя или любая другая → текст .txt.

Дальше текст идёт обычным путём ingest, как загруженный файл. В вакансии нет персональных данных,
поэтому загрузка страницы — не внешний вызов LLM и идёт мимо `llm/client.py` (принцип 4 про LLM).

Защита: только http и https, адреса внутренней сети и localhost запрещены (в том числе после
перенаправления), размер страницы ограничен `max_file_mb`, время — `url_timeout_s`.
"""

from __future__ import annotations

import ipaddress
import re
import socket
from urllib.parse import urljoin, urlsplit

import httpx
import lxml.html
from charset_normalizer import from_bytes

from aihr.config import get_settings

MAX_REDIRECTS = 5
_USER_AGENT = "Mozilla/5.0 (compatible; AIHR vacancy import)"
_DROP = ("script", "style", "noscript", "svg", "iframe", "template", "header", "footer", "nav",
         "form", "button", "select")  # fmt: skip
_BLOCKS = {"h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "dt", "dd", "tr", "blockquote", "pre"}
_SPACES = re.compile(r"[ \t   ]+")
_BAD_NAME = re.compile(r'[\\/:*?"<>|\r\n\t]+')
_META_CHARSET = re.compile(rb"<meta[^>]+charset\s*=\s*[\"']?([\w-]+)", re.IGNORECASE)
# hh.ru: описание, требуемый опыт и ключевые навыки лежат в блоках с data-qa
_HH_TITLE = '//*[@data-qa="vacancy-title"]'
_HH_PARTS = (
    ("Требуемый опыт работы", '//*[@data-qa="vacancy-experience"]'),
    ("График", '//*[@data-qa="work-schedule-by-days-text"]'),
)
_HH_BODY = '//*[@data-qa="vacancy-description"]'
_HH_SKILLS = '//*[@data-qa="skills-element"]'


class UrlImportError(ValueError):
    """Страницу нельзя превратить в вакансию; текст ошибки — для рекрутера."""


def _check_host(url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise UrlImportError("Нужна ссылка вида https://…")
    try:
        infos = socket.getaddrinfo(parts.hostname, parts.port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise UrlImportError(
            f"Сайт {parts.hostname} не найден. Проверьте ссылку и доступ в интернет."
        ) from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global:
            raise UrlImportError("Ссылки на адреса внутренней сети и localhost не загружаем.")


def fetch_page(url: str) -> tuple[bytes, str]:
    """(байты HTML, итоговый адрес). Каждое перенаправление проверяет _check_host."""
    s = get_settings()
    limit = s.max_file_bytes
    current = url.strip()
    with httpx.Client(
        timeout=s.url_timeout_s, follow_redirects=False, headers={"User-Agent": _USER_AGENT}
    ) as client:
        for _ in range(MAX_REDIRECTS + 1):
            _check_host(current)
            try:
                with client.stream("GET", current) as resp:
                    if resp.is_redirect and resp.headers.get("location"):
                        current = urljoin(current, resp.headers["location"])
                        continue
                    if resp.status_code != 200:
                        raise UrlImportError(
                            f"Сайт ответил {resp.status_code}. Откройте ссылку в браузере или "
                            "загрузите вакансию файлом."
                        )
                    data = b""
                    for chunk in resp.iter_bytes():
                        data += chunk
                        if len(data) > limit:
                            raise UrlImportError(f"Страница больше {s.max_file_mb:g} МБ.")
                    return data, current
            except httpx.TimeoutException as exc:
                raise UrlImportError(
                    f"Сайт не ответил за {s.url_timeout_s:g} с. Загрузите вакансию файлом."
                ) from exc
            except httpx.HTTPError as exc:
                raise UrlImportError(
                    "Не удалось открыть ссылку. Проверьте доступ в интернет или загрузите файлом."
                ) from exc
    raise UrlImportError("Слишком много перенаправлений.")


def _clean(text: str) -> str:
    lines = (_SPACES.sub(" ", line).strip() for line in text.split("\n"))
    return "\n".join(line for line in lines if line)


def _block_lines(root: lxml.html.HtmlElement) -> list[str]:
    """Абзацы, заголовки и пункты списков по порядку; пункт списка — с «- »."""
    blocks = [
        el
        for el in root.iter(*_BLOCKS)
        if not any(child.tag in _BLOCKS for child in el.iterdescendants())
    ]
    if not blocks:
        return [line for line in _clean(root.text_content()).split("\n") if line]
    lines: list[str] = []
    for el in blocks:
        text = _clean(el.text_content())
        if not text:
            continue
        in_list = el.tag == "li" or any(a.tag == "li" for a in el.iterancestors())
        for i, line in enumerate(text.split("\n")):
            lines.append(f"- {line}" if in_list and i == 0 else line)
    return lines


def _first_text(doc: lxml.html.HtmlElement, xpath: str) -> str:
    found = doc.xpath(xpath)
    return _clean(found[0].text_content()).replace("\n", " ") if found else ""


def _decode(html: bytes) -> str:
    """Кодировка из <meta charset>, иначе UTF-8, иначе угадывает charset-normalizer."""
    declared = _META_CHARSET.search(html[:4096])
    for enc in ([declared.group(1).decode("ascii")] if declared else []) + ["utf-8"]:
        try:
            return html.decode(enc)
        except (LookupError, UnicodeDecodeError):
            continue
    best = from_bytes(html).best()
    return str(best) if best else html.decode("utf-8", errors="replace")


def page_to_text(html: bytes) -> tuple[str, str]:
    """(название, текст вакансии). Название — заголовок страницы, текст — с названием в начале."""
    doc = lxml.html.document_fromstring(_decode(html))
    for br in doc.iter("br"):
        br.tail = "\n" + (br.tail or "")
    body_hh = doc.xpath(_HH_BODY)
    if body_hh:
        title = _first_text(doc, _HH_TITLE)
        lines = [
            value if value.startswith(label) else f"{label}: {value}"
            for label, xp in _HH_PARTS
            if (value := _first_text(doc, xp))
        ]
        lines += _block_lines(body_hh[0])
        skills = [_clean(el.text_content()) for el in doc.xpath(_HH_SKILLS)]
        if skills:
            lines += ["Ключевые навыки:", *(f"- {skill}" for skill in skills if skill)]
    else:
        for el in list(doc.iter(*_DROP)):
            if el.getparent() is not None:
                el.drop_tree()
        h1 = doc.xpath("//h1")
        title = _clean(h1[0].text_content()).replace("\n", " ") if h1 else ""
        if not title:
            title = _first_text(doc, "//title")
        main = doc.xpath("//main") or doc.xpath("//article") or doc.xpath("//body") or [doc]
        lines = _block_lines(main[0])
    if title and (not lines or lines[0] != title):
        lines.insert(0, title)
    return title, "\n".join(lines)


def safe_filename(title: str, fallback: str = "вакансия") -> str:
    name = _SPACES.sub(" ", _BAD_NAME.sub(" ", title)).strip(" .")[:80].strip() or fallback
    return f"{name}.txt"


def fetch_vacancy(url: str) -> tuple[bytes, str, str]:
    """(текст .txt в UTF-8, имя файла, итоговый адрес)."""
    html, final = fetch_page(url)
    try:
        title, text = page_to_text(html)
    except (ValueError, lxml.etree.ParserError) as exc:
        raise UrlImportError("Страница не похожа на HTML. Загрузите вакансию файлом.") from exc
    if len(text) < 200:
        raise UrlImportError(
            "На странице не нашли текст вакансии: возможно, он подгружается скриптом или нужен "
            "вход на сайт. Скачайте вакансию и загрузите файлом."
        )
    return text.encode("utf-8"), safe_filename(title), final
