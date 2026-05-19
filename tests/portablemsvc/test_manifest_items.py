import logging

from portablemsvc.manifest_items import resolve_redist_packages


def test_resolve_redist_package_uses_generic_dependency_without_missing_warning(caplog):
    packages = {
        "microsoft.visualcpp.crt.redist.x64": [
            {
                "dependencies": [
                    "microsoft.vc.14.44.17.14.crt.redist.x64.base",
                ],
            },
        ],
        "microsoft.vc.14.44.17.14.crt.redist.x64.base": [
            {
                "payloads": [],
            },
        ],
    }
    requested = [
        "microsoft.vc.14.43.17.13.crt.redist.x64.base",
    ]

    with caplog.at_level(logging.WARNING):
        resolved = resolve_redist_packages(
            packages,
            requested,
            "14.43.17.13",
            ["x64"],
        )

    assert resolved == ["microsoft.vc.14.44.17.14.crt.redist.x64.base"]
    assert not caplog.records
