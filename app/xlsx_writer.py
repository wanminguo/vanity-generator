#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
零依赖 XLSX 写入器。

xlsx 本质是一个 zip 包，里面装若干 XML。这里只用标准库 zipfile 手工拼装，
不依赖 openpyxl / xlsxwriter，保持项目「零第三方依赖」的约束。

支持：单个工作表、表头加粗带底色、列宽、文本与数值单元格。
"""

import re
import zipfile
from datetime import datetime
from xml.sax.saxutils import escape

CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
DOC_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

INVALID_XML_CHARS = re.compile(
    "[\x00-\x08\x0b\x0c\x0e-\x1f]"
)


def _clean(text):
    """xlsx 的 XML 不允许控制字符，先清掉再转义"""
    return escape(INVALID_XML_CHARS.sub("", str(text)))


def _col_letter(index):
    """1 → A, 26 → Z, 27 → AA"""
    out = ""
    while index > 0:
        index, rem = divmod(index - 1, 26)
        out = chr(65 + rem) + out
    return out


def _content_types():
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<Types xmlns="{CT_NS}">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '<Override PartName="/xl/styles.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        "</Types>"
    )


def _root_rels():
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<Relationships xmlns="{REL_NS}">'
        f'<Relationship Id="rId1" Type="{DOC_REL}/officeDocument" Target="xl/workbook.xml"/>'
        "</Relationships>"
    )


def _workbook(sheet_name):
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<workbook xmlns="{MAIN_NS}" xmlns:r="{DOC_REL}">'
        "<sheets>"
        f'<sheet name="{_clean(sheet_name)[:31]}" sheetId="1" r:id="rId1"/>'
        "</sheets>"
        "</workbook>"
    )


def _workbook_rels():
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<Relationships xmlns="{REL_NS}">'
        f'<Relationship Id="rId1" Type="{DOC_REL}/worksheet" Target="worksheets/sheet1.xml"/>'
        f'<Relationship Id="rId2" Type="{DOC_REL}/styles" Target="styles.xml"/>'
        "</Relationships>"
    )


def _styles():
    # s=0 默认，s=1 表头（加粗 + 深色底 + 白字），s=2 私钥等敏感列（等宽感 + 浅底）
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<styleSheet xmlns="{MAIN_NS}">'
        '<fonts count="2">'
        '<font><sz val="11"/><name val="Calibri"/></font>'
        '<font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Calibri"/></font>'
        "</fonts>"
        '<fills count="3">'
        '<fill><patternFill patternType="none"/></fill>'
        '<fill><patternFill patternType="gray125"/></fill>'
        '<fill><patternFill patternType="solid"><fgColor rgb="FF1F3140"/><bgColor indexed="64"/></patternFill></fill>'
        "</fills>"
        '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        '<cellXfs count="2">'
        '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
        '<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/>'
        "</cellXfs>"
        "</styleSheet>"
    )


def _sheet(headers, rows, widths, freeze_header=True):
    cols = ""
    if widths:
        cols = "<cols>" + "".join(
            f'<col min="{i + 1}" max="{i + 1}" width="{w}" customWidth="1"/>'
            for i, w in enumerate(widths)
        ) + "</cols>"

    parts = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
             f'<worksheet xmlns="{MAIN_NS}">']
    if freeze_header:
        parts.append('<sheetViews><sheetView workbookViewId="0">'
                     '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
                     "</sheetView></sheetViews>")
    parts.append(cols)
    parts.append("<sheetData>")

    # 表头
    cells = []
    for i, h in enumerate(headers):
        ref = f"{_col_letter(i + 1)}1"
        cells.append(f'<c r="{ref}" s="1" t="inlineStr"><is><t>{_clean(h)}</t></is></c>')
    parts.append('<row r="1">' + "".join(cells) + "</row>")

    # 数据行
    for r, row in enumerate(rows, start=2):
        cells = []
        for i, value in enumerate(row):
            if value is None or value == "":
                continue
            ref = f"{_col_letter(i + 1)}{r}"
            if isinstance(value, bool):
                cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{int(value)}</t></is></c>')
            elif isinstance(value, (int, float)):
                cells.append(f'<c r="{ref}" t="n"><v>{value}</v></c>')
            else:
                cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{_clean(value)}</t></is></c>')
        parts.append(f'<row r="{r}">' + "".join(cells) + "</row>")

    parts.append("</sheetData></worksheet>")
    return "".join(parts)


def write_xlsx(path, sheet_name, headers, rows, widths=None):
    """写出 xlsx。rows 为二维序列，元素支持 str / int / float / None。"""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", _content_types())
        zf.writestr("_rels/.rels", _root_rels())
        zf.writestr("xl/workbook.xml", _workbook(sheet_name))
        zf.writestr("xl/_rels/workbook.xml.rels", _workbook_rels())
        zf.writestr("xl/styles.xml", _styles())
        zf.writestr("xl/worksheets/sheet1.xml", _sheet(headers, rows, widths))


def default_filename(prefix="vanity"):
    return f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"


if __name__ == "__main__":
    write_xlsx(
        r"D:\Web3靓号生成器\docs\_xlsx_selftest.xlsx",
        "自检",
        ["序号", "链条", "地址", "私钥", "尝试次数", "备注"],
        [
            [1, "ETH", "0x7404b894A4D3AB7f6Eba0f07cc0548e77F7C7888", "a" * 64, 512, "含 & < > 的中文"],
            [2, "BTC", "1BgGZ9tcN4rm9KBzDn7KprQz87SZ26SAMH", "0" * 63 + "1", 18, ""],
        ],
        [6, 10, 44, 70, 12, 20],
    )
    print("written")
