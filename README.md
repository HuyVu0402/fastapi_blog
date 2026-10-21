# FastAPI Blog

## Chạy local bằng uv

```bash
uv sync --locked
test -f .env || cp .env.example .env
```

Đặt `SECRET_KEY` ngẫu nhiên trong `.env`. `DATABASE_URL` mặc định là
`sqlite+aiosqlite:///./blog.db`. Để dùng PostgreSQL, tạo database trước và cấu hình:

```dotenv
DATABASE_URL=postgresql+psycopg://blog_user:password@localhost:5432/blog
```

Với database mới:

```bash
uv run alembic upgrade head
```

Với SQLite từ part 14 đã có dữ liệu, dừng server rồi chạy:

```bash
uv run python scripts/adopt_sqlite.py
uv run python scripts/adopt_sqlite.py --upgrade
```

Script kiểm tra schema, tạo bản sao `*.pre-alembic-*.sqlite3` cạnh database,
đánh dấu migration ban đầu và thêm cột `posts.likes` với giá trị mặc định `0`.
Script từ chối schema không khớp; không dùng `alembic stamp` tùy ý trên database khác.
Database đã được Alembic quản lý chỉ cần `uv run alembic upgrade head`.

```bash
source .venv/bin/activate
uv run fastapi dev main.py
```

Ứng dụng không tự tạo bảng khi khởi động nữa. Kiểm tra schema bằng
`uv run alembic current` và `uv run alembic check`.

SMTP được cấu hình theo `.env.example` để gửi email đặt lại mật khẩu.
Không commit `.env`, database hoặc bản sao lưu.

Part 15 tích hợp từ
[CoreyMSchafer/FastAPI-15-Postgres-Alembic](https://github.com/CoreyMSchafer/FastAPI-15-Postgres-Alembic/commit/891ad80d6cf0b2cb6a30c83f0e2a2e449f97754d).

## Ảnh đại diện trên S3 (part 16)

Không đặt `S3_BUCKET_NAME`: ảnh tiếp tục được lưu trong `media/profile_pics`.
Để dùng S3, cấu hình `S3_BUCKET_NAME` và `S3_REGION` trong `.env`.
Ứng dụng dùng AWS credential chain mặc định (ví dụ IAM role hoặc AWS profile),
hoặc hai biến `S3_ACCESS_KEY_ID` và `S3_SECRET_ACCESS_KEY` nếu được cung cấp.

Ảnh được chuyển thành JPEG 300×300, upload vào `profile_pics/<uuid>.jpg` và
xóa khi thay ảnh, xóa ảnh hoặc xóa tài khoản. Boto3 chạy trong threadpool.
Nếu upload thất bại, ảnh đang dùng không bị thay đổi. Lỗi dọn ảnh sau khi lưu
database được ghi log để xử lý, không khiến thao tác đã lưu báo thất bại.

Hai file `docs/aws_iam_policy.json` và `docs/aws_bucket_policy.json` là mẫu:
thay `YOUR_BUCKET_NAME` bằng tên bucket thực tế. IAM cần quyền ghi/xóa ảnh;
bucket policy mẫu cho phép đọc công khai riêng prefix `profile_pics/`, như bài học.
Bucket phải cho phép chính sách đọc đó, hoặc cấu hình CDN để phục vụ ảnh.
Ứng dụng hiện trả URL công khai, không tạo presigned URL cho bucket private.

`S3_ENDPOINT_URL` dùng cho dịch vụ tương thích S3; `S3_PUBLIC_URL` là URL gốc
của bucket/CDN phục vụ ảnh (không kèm `/profile_pics`). Khi chuyển local sang S3,
cần chuyển ảnh hiện hữu sang prefix `profile_pics/` với nguyên tên file trước
khi bật bucket; ứng dụng không tự di chuyển ảnh cũ. Chuyển ngược lại cũng cần
đồng bộ ảnh về local.

Part 16 tích hợp từ
[CoreyMSchafer/FastAPI-16-AWS-S3-Image-Uploads](https://github.com/CoreyMSchafer/FastAPI-16-AWS-S3-Image-Uploads/commit/e79a99bfe2f77fcea423cf5df34be9db1eb8d5ed).

## Kiểm thử (part 17)

```bash
uv sync --locked
uv run pytest -q
```

`pytest` và `moto[s3]` thuộc nhóm dependency `dev`. Bộ test giữ 12 bài từ
tutorial và bổ sung kiểm tra phân trang, token hết hạn/dùng lại, đổi mật khẩu,
phân quyền ảnh, lỗi storage, rollback upload và chế độ lưu ảnh local.

Mỗi test có SQLite tạm riêng và session mới cho từng request. S3 dùng Moto,
email được mock, ảnh local chỉ ghi vào thư mục tạm. Không cần PostgreSQL,
AWS hay SMTP thật; không dùng hoặc xóa bảng trong `blog.db`. Bộ test này
không thay thế việc kiểm thử tích hợp với PostgreSQL và AWS thực tế.

```bash
uv run pytest tests/test_users.py -q
uv run pytest tests/test_regressions.py -q
```

Part 17 tích hợp từ
[CoreyMSchafer/FastAPI-17-Testing](https://github.com/CoreyMSchafer/FastAPI-17-Testing/commit/f8e78e674574e6b1a69a135dfc84ae929b55bc36).

## Triển khai VPS (part 18)

Xem [hướng dẫn VPS](docs/deployment-vps.md) và hai mẫu trong `deploy/` cho
systemd chạy bằng uv, Nginx và HTTPS. Endpoint `/health` kiểm tra kết nối database:
HTTP 200 khi hoạt động, HTTP 503 khi database không sẵn sàng; cả hai trả JSON.
Part này không thêm dependency Python.

## Docker và Cloud Run (part 19)

Xem [hướng dẫn Docker/Cloud Run](docs/deployment-cloud-run.md). Dockerfile dùng
uv, chạy non-root, đọc `PORT` và giữ credentials bên ngoài image. Ứng dụng bổ sung
security headers và giữ chính sách referrer riêng cho trang reset mật khẩu.

Part này đã kiểm tra code/cấu hình và test Python, **chưa build/chạy Docker hoặc
triển khai Cloud Run**. Không thêm dependency Python.
