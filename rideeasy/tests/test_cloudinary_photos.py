import hashlib
import io
import time

from PIL import Image

from app.services.cloudinary_service import CloudinaryService


def _sample_image():
    image = Image.new("RGB", (600, 600), color=(45, 110, 180))
    data = io.BytesIO()
    image.save(data, format="PNG")
    data.seek(0)
    return data


def test_cloudinary_upload_uses_signed_server_request(app, monkeypatch):
    class Response:
        def raise_for_status(self):
            pass

        @staticmethod
        def json():
            return {
                "public_id": "rideeasy/avatars/user-id",
                "secure_url": "https://demo-cloud.res.cloudinary.com/image/upload/avatar.jpg",
            }

    monkeypatch.setitem(app.config, "CLOUDINARY_CLOUD_NAME", "demo-cloud")
    monkeypatch.setitem(app.config, "CLOUDINARY_API_KEY", "test-api-key")
    monkeypatch.setitem(app.config, "CLOUDINARY_API_SECRET", "test-api-secret")
    captured = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return Response()

    monkeypatch.setattr("app.services.cloudinary_service.requests.post", fake_post)
    with app.app_context():
        result = CloudinaryService.upload(b"cleaned-image", "rideeasy/avatars", "user-id")

    params = captured["data"]
    unsigned = {
        key: params[key]
        for key in ("folder", "overwrite", "public_id", "timestamp")
    }
    expected_signature = hashlib.sha1(
        ("&".join(f"{key}={unsigned[key]}" for key in sorted(unsigned)) + "test-api-secret").encode()
    ).hexdigest()
    assert captured["url"] == "https://api.cloudinary.com/v1_1/demo-cloud/image/upload"
    assert params["api_key"] == "test-api-key"
    assert params["signature"] == expected_signature
    assert int(params["timestamp"]) <= int(time.time())
    assert result["public_id"] == "rideeasy/avatars/user-id"


def test_driver_vehicle_photos_are_cloud_hosted_and_visible_to_matched_passenger(
    client, db, monkeypatch
):
    client.get("/auth/demo/driver", follow_redirects=True)
    monkeypatch.setattr(
        "app.services.cloudinary_service.CloudinaryService.upload",
        lambda image_bytes, folder, public_id: {
            "public_id": f"{folder}/{public_id}",
            "secure_url": f"https://demo-cloud.res.cloudinary.com/{folder}/{public_id}.jpg",
        },
    )
    with client.session_transaction() as session:
        csrf_token = session["payment_csrf_token"]
    response = client.post(
        "/driver/vehicle-photos",
        data={
            "csrf_token": csrf_token,
            "photo_FRONT": (_sample_image(), "front.png"),
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 302

    photo = db.fetchone(
        "SELECT cloudinary_public_id, cloudinary_url, image_data FROM vehicle_photos "
        "WHERE vehicle_id = ? AND slot = ?",
        ("veh_01", "FRONT"),
    )
    assert photo["cloudinary_public_id"] == "rideeasy/vehicles/veh_01/front"
    assert photo["cloudinary_url"].startswith("https://demo-cloud.res.cloudinary.com/")
    assert photo["image_data"] == ""

    client.get("/auth/demo/passenger", follow_redirects=True)
    monkeypatch.setattr(
        "app.services.cloudinary_service.CloudinaryService.fetch",
        lambda image_url: {"mime_type": "image/jpeg", "data": b"cloud-photo"},
    )
    trip = client.get("/passenger/rides/ride_01")
    assert trip.status_code == 200
    assert b"Your driver's vehicle" in trip.data
    assert b"FRONT.jpg" in trip.data

    photo_response = client.get("/vehicle-photos/veh_01/FRONT.jpg")
    assert photo_response.status_code == 200
    assert photo_response.data == b"cloud-photo"


def test_profile_picture_is_uploaded_to_cloudinary_and_used_for_current_user(
    client, db, monkeypatch
):
    client.get("/auth/demo/passenger", follow_redirects=True)
    monkeypatch.setattr(
        "app.routes.profile.CloudinaryService.upload",
        lambda image_bytes, folder, public_id: {
            "public_id": f"{folder}/{public_id}",
            "secure_url": "https://demo-cloud.res.cloudinary.com/profile/avatar.jpg",
        },
    )
    response = client.post(
        "/profile",
        data={
            "full_name": "Grace Namubiru",
            "email": "passenger@rideeasy.ug",
            "phone": "+256 772 123 456",
            "avatar": (_sample_image(), "profile.png"),
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert response.status_code == 200
    passenger = db.fetchone(
        "SELECT avatar_url, avatar_cloudinary_public_id FROM users WHERE id = ?",
        ("usr_pass_01",),
    )
    assert passenger["avatar_url"] == "https://demo-cloud.res.cloudinary.com/profile/avatar.jpg"
    assert passenger["avatar_cloudinary_public_id"].startswith("rideeasy/avatars/usr_pass_01_")
    assert b"https://demo-cloud.res.cloudinary.com/profile/avatar.jpg" in response.data
