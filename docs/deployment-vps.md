# Triển khai VPS bằng uv, systemd và Nginx

Hướng dẫn cho VPS Ubuntu 24.04 có systemd. Các lệnh bên dưới chạy trên VPS,
không phải yêu cầu triển khai tự động. Thay domain `blog.example.com` bằng domain
thực tế. Mẫu dùng user `blog`, thư mục `/srv/fastapi-blog` và uv tại
`/home/blog/.local/bin/uv`; nếu đổi các giá trị này, sửa cả file service và Nginx.

## Chuẩn bị server

Dùng SSH key và tài khoản quản trị có sudo. Nếu thay đổi cấu hình SSH, kiểm tra
đăng nhập bằng phiên thứ hai trước khi đóng phiên hiện tại. Trỏ DNS domain về VPS.

```bash
sudo apt update
sudo apt install git python3 python3-venv curl nginx postgresql certbot python3-certbot-nginx
sudo adduser blog
sudo mkdir -p /srv/fastapi-blog
sudo chown blog:blog /srv/fastapi-blog
```

Firewall cần cho phép cổng SSH đang sử dụng và HTTP/HTTPS. Không mở 8000 hay
PostgreSQL ra Internet với cấu hình một VPS này. Ví dụ nếu dùng UFW và SSH cổng 22:

```bash
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'
sudo ufw enable
```

Tạo role/database PostgreSQL; `\password` hỏi mật khẩu thay vì ghi vào câu SQL:

```bash
sudo -u postgres psql
```

```sql
CREATE USER blog_user;
\password blog_user
CREATE DATABASE blog OWNER blog_user;
\q
```

## Cài ứng dụng

Chuyển sang user ứng dụng, cài uv và clone repo:

```bash
sudo -iu blog
curl -LsSf https://astral.sh/uv/install.sh -o /tmp/install-uv.sh
sh /tmp/install-uv.sh
export PATH="$HOME/.local/bin:$PATH"
git clone https://github.com/HuyVu0402/fastapi_blog.git /srv/fastapi-blog
cd /srv/fastapi-blog
uv sync --locked --no-dev
test -f .env || cp .env.example .env
chmod 600 .env
uv run --no-dev python -c 'import secrets; print(secrets.token_urlsafe(32))'
```

Sửa `.env`: đặt SECRET_KEY vừa sinh, DATABASE_URL với driver `postgresql+psycopg`,
`FRONTEND_URL=https://blog.example.com`, SMTP và S3 theo README. Percent-encode
ký tự đặc biệt trong username/password của database URL. Không thay SECRET_KEY
mỗi lần deploy. S3 là tùy chọn; nếu lưu local, giữ và sao lưu `media/profile_pics/`.

```bash
uv run --locked --no-dev alembic upgrade head
uv run --locked --no-dev alembic check
mkdir -p media/profile_pics
chmod 755 /srv/fastapi-blog
find static -type d -exec chmod 755 {} \;
find static -type f -exec chmod 644 {} \;
exit
```

Nginx chỉ cần quyền đọc `static/`. File `.env` vẫn chỉ user `blog` được đọc.
Migrations chạy trước khi bật service, không chạy trong từng worker.

## Bật service và reverse proxy

Từ tài khoản quản trị:

```bash
sudo cp /srv/fastapi-blog/deploy/fastapi-blog.service /etc/systemd/system/
sudo systemd-analyze verify /etc/systemd/system/fastapi-blog.service
sudo systemctl daemon-reload
sudo systemctl enable --now fastapi-blog
curl --fail http://127.0.0.1:8000/health
sudo cp /srv/fastapi-blog/deploy/nginx.conf /etc/nginx/sites-available/fastapi-blog
sudoedit /etc/nginx/sites-available/fastapi-blog
```

Đổi `server_name` thành domain thực tế, rồi bật site:

```bash
sudo ln -s /etc/nginx/sites-available/fastapi-blog /etc/nginx/sites-enabled/fastapi-blog
sudo nginx -t
sudo systemctl reload nginx
sudo certbot --nginx -d blog.example.com --redirect
sudo certbot renew --dry-run
curl --fail https://blog.example.com/health
```

Mẫu Nginx ban đầu dùng HTTP để cấp chứng chỉ; Certbot bổ sung HTTPS và redirect.
Chỉ sử dụng đăng nhập/upload từ Internet sau khi HTTPS hoạt động. Không ghi đè
cấu hình Nginx do Certbot đã chỉnh khi cập nhật source. FastAPI chỉ tin proxy
headers từ `127.0.0.1`, đúng địa chỉ Nginx trong mẫu này.

`/health` trả `{"status":"healthy"}` với HTTP 200 khi `SELECT 1` thành công,
hoặc `{"detail":"Database unavailable"}` với HTTP 503. Endpoint kiểm tra kết nối
database, không xác nhận migrations, SMTP hay S3; dùng thêm `alembic check` và
kiểm thử chức năng tương ứng trước khi đưa bản mới vào sử dụng.

## Cập nhật và theo dõi

Chạy test trên máy phát triển/CI trước khi deploy. Sao lưu PostgreSQL và ảnh local
trước migration, dừng service trong đợt cập nhật này, rồi chạy dưới user `blog`:

```bash
sudo systemctl stop fastapi-blog
sudo -iu blog
cd /srv/fastapi-blog
git pull --ff-only
uv sync --locked --no-dev
uv run --locked --no-dev alembic upgrade head
uv run --locked --no-dev alembic check
exit
sudo systemctl start fastapi-blog
curl --fail http://127.0.0.1:8000/health
sudo systemctl status fastapi-blog
sudo journalctl -u fastapi-blog -n 100 --no-pager
```

Nếu migration thất bại, kiểm tra log và bản sao lưu trước khi khởi động lại;
không tự động downgrade vì migration khác có thể mất dữ liệu. Thiết lập lịch
sao lưu và kiểm tra khôi phục theo môi trường vận hành của bạn.

Nguồn: [Part 18, commit 4af7f79](https://github.com/CoreyMSchafer/FastAPI-18-Deployment-VPS/commit/4af7f79d92ebf5c9b1d369a7be7299f1c0cb8e17).
