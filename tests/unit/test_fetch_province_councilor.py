from src.fetch_province_councilor import parse_table_rows


def test_parse_table_rows() -> None:
    rows = [
        ["地區", "姓名", "號次", "性別", "出生年次", "推薦政黨", "得票數", "得票率", "當選", "現任"],
        [
            "臺北縣",
            "地區臺北縣，楊泰順，新黨，號次1，得票數123448，得票率8.09%，當選。\n楊泰順\n"
            "地區臺北縣，苗素芳，中國國民黨，號次2，得票數44038，得票率2.88%，現任。\n苗素芳",
            "1\n2",
            "男\n女",
            "1953\n1928",
            "地區臺北縣，新黨，號次1，得票數123448，第一階段得票率undefined，第二階段得票率undefined，分配席次undefined。\n新黨\n"
            "地區臺北縣，中國國民黨，號次2，得票數44038，第一階段得票率undefined，第二階段得票率undefined，分配席次undefined。\n中國國民黨",
            "123,448\n44,038",
            "8.09%\n2.88%",
            "*",
            "是",
        ],
    ]

    records = parse_table_rows(rows)

    assert records == [
        {
            "name": "楊泰順",
            "birthday": 1953,
            "order_id": 1,
            "party": "新黨",
            "year": 1994,
            "region": "臺北縣",
            "type": "臺灣省議員",
            "elected": 1,
        },
        {
            "name": "苗素芳",
            "birthday": 1928,
            "order_id": 2,
            "party": "中國國民黨",
            "year": 1994,
            "region": "臺北縣",
            "type": "臺灣省議員",
            "elected": 0,
        },
    ]


def test_parse_table_rows_region_override_and_independent_elected() -> None:
    rows = [
        ["地區", "姓名", "號次", "性別", "出生年次", "推薦政黨", "得票數", "得票率", "當選", "現任"],
        [
            "臺灣省",
            "地區臺灣省，黃金文，民主進步黨，號次1，得票數6131，得票率19.9%。\n黃金文\n"
            "地區臺灣省，楊仁福，中國國民黨，號次2，得票數24680，得票率80.1%，當選，現任。\n楊仁福",
            "1\n2",
            "男\n男",
            "1947\n1942",
            "地區臺灣省，民主進步黨，號次1，得票數6131，第一階段得票率undefined，第二階段得票率undefined，分配席次undefined。\n民主進步黨\n"
            "地區臺灣省，中國國民黨，號次2，得票數24680，第一階段得票率undefined，第二階段得票率undefined，分配席次undefined。\n中國國民黨",
            "6,131\n24,680",
            "19.90%\n80.10%",
            "*",
            "是",
        ],
    ]

    records = parse_table_rows(rows, region_override="平地原住民北區")

    assert [record["region"] for record in records] == ["平地原住民北區", "平地原住民北區"]
    assert [record["elected"] for record in records] == [0, 1]
