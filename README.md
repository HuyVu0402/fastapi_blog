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
