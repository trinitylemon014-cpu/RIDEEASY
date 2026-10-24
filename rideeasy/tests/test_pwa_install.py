import json


def test_install_shortcut_button_and_manifest_assets_are_available(client):
    page = client.get("/")
    assert page.status_code == 200
    assert page.data.count(b'data-install-app') == 2
    assert b'id="app-install-help"' in page.data
    assert b'<link rel="manifest" href="/static/manifest.json">' in page.data

    manifest_response = client.get("/static/manifest.json")
    assert manifest_response.status_code == 200
    manifest = json.loads(manifest_response.data)
    assert manifest["display"] == "standalone"
    assert manifest["start_url"] == "/?source=installed-app"
    assert manifest["icons"][0]["src"] == "/static/icons/rideeasy-icon.svg"

    icon_response = client.get(manifest["icons"][0]["src"])
    assert icon_response.status_code == 200
    assert b"<svg" in icon_response.data


def test_install_controls_and_instruction_styles_are_served(client):
    javascript = client.get("/static/js/app.js")
    assert javascript.status_code == 200
    assert b"beforeinstallprompt" in javascript.data
    assert b"Add to Home Screen" in javascript.data

    stylesheet = client.get("/static/css/components.css")
    assert stylesheet.status_code == 200
    assert b".app-install-button" in stylesheet.data
    assert b".app-install-dialog" in stylesheet.data
