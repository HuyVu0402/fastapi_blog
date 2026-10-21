# Docker và Google Cloud Run (part 19)

Các lệnh dưới đây là hướng dẫn triển khai thủ công. Trong lần tích hợp này chỉ
kiểm tra code/cấu hình và chạy test Python; chưa build/chạy Docker hay deploy cloud.

## Container

Dockerfile dùng hai stage Python 3.12, cùng phiên bản minor với `.python-version`.
uv cài dependency từ lockfile với `--no-dev`; runtime chạy user không phải root,
lắng nghe `0.0.0.0:$PORT` (mặc định 8080). Các file được COPY theo danh sách cụ thể;
`.env`, AWS credentials, database, bản sao lưu và ảnh upload không nằm trong image.
Migrations có sẵn trong image nhưng phải chạy riêng trước khi khởi động service.

Các lệnh tham khảo khi bạn muốn tự kiểm tra Docker sau này:

```bash
docker build -t fastapi-blog:part19 .
docker run --rm --env-file .env fastapi-blog:part19 \
  uv run --locked --no-sync --no-dev alembic upgrade head
docker run --rm --env-file .env -p 127.0.0.1:8080:8080 fastapi-blog:part19
```

Với ví dụ này, `.env` phải trỏ đến PostgreSQL truy cập được từ container và S3.
`localhost` trong container là chính container, không phải database trên host.
SQLite/ảnh local sẽ mất khi container bị xóa nếu không có volume; Cloud Run dùng
PostgreSQL bên ngoài và S3, không dùng SQLite hay ảnh trên filesystem container
làm kho dữ liệu lâu dài. [Hợp đồng runtime Cloud Run](https://cloud.google.com/run/docs/container-contract).

Dockerfile tin proxy headers từ localhost theo mặc định. Chỉ đặt
`FORWARDED_ALLOW_IPS=*` khi container nằm sau proxy kiểm soát được như Cloud Run;
không dùng giá trị này với container được truy cập trực tiếp từ Internet.

## Chuẩn bị Cloud Run

Dùng Google Cloud CLI đã đăng nhập và project có billing. Chuẩn bị:

- Artifact Registry dạng Docker, cùng region triển khai.
- Service account cho ứng dụng, ví dụ `blog-runtime`, được cấp quyền đọc đúng
  các secret cần dùng qua `roles/secretmanager.secretAccessor`.
- PostgreSQL đã tạo database/user và cấu hình kết nối từ cả service lẫn migration
  job. Nếu dùng Cloud SQL/private IP, thêm cấu hình Cloud SQL/VPC tương ứng cho
  cả hai lệnh bên dưới; không chỉ đổi DATABASE_URL.
- S3 bucket/policy theo README, SMTP, domain/URL HTTPS cho `FRONTEND_URL`.
- Secret Manager chứa các secret `blog-secret-key`, `blog-database-url`,
  `blog-s3-access-key`, `blog-s3-secret-key`, `blog-mail-password`. Ví dụ bên dưới
  chọn version `1`; thay bằng version đã tạo. Không ghi secret vào Dockerfile.

Cloud Run service account không tự trở thành AWS IAM role. Ví dụ này cấp AWS
credentials qua Secret Manager; quyền AWS giới hạn theo mẫu policy trong `docs/`.
[Cấu hình secrets cho Cloud Run](https://cloud.google.com/run/docs/configuring/services/secrets).

## Build và đẩy image khi triển khai

Thay các giá trị mẫu trước khi chạy. Dùng tag riêng cho từng commit; khi cần build
tái lập tuyệt đối, pin digest của base images sau khi xác nhận trên registry.

```bash
APP_PROJECT=your-project-id
APP_REGION=asia-southeast1
APP_REPOSITORY=fastapi-blog
APP_TAG=$(git rev-parse --short HEAD)
APP_IMAGE="$APP_REGION-docker.pkg.dev/$APP_PROJECT/$APP_REPOSITORY/blog:$APP_TAG"
APP_SERVICE_ACCOUNT="blog-runtime@$APP_PROJECT.iam.gserviceaccount.com"

gcloud config set project "$APP_PROJECT"
gcloud auth configure-docker "$APP_REGION-docker.pkg.dev"
docker build --platform linux/amd64 -t "$APP_IMAGE" .
docker push "$APP_IMAGE"
```

Registry và service account phải được tạo trước. Các lệnh này không tự cấp quyền
IAM hoặc tạo database/secrets. [Triển khai image lên Cloud Run](https://cloud.google.com/run/docs/deploying).

## Migration job trước, service sau

Sao lưu database trước khi chạy migration của một bản cập nhật:

```bash
gcloud run jobs deploy fastapi-blog-migrate \
  --image "$APP_IMAGE" --region "$APP_REGION" \
  --service-account "$APP_SERVICE_ACCOUNT" \
  --tasks 1 --parallelism 1 --max-retries 0 \
  --command /bin/uv \
  --args run,--locked,--no-sync,--no-dev,alembic,upgrade,head \
  --set-secrets SECRET_KEY=blog-secret-key:1,DATABASE_URL=blog-database-url:1

gcloud run jobs execute fastapi-blog-migrate --region "$APP_REGION" --wait
```

Chỉ deploy service khi job thành công. Không chạy migration tự động ở mỗi instance
vì nhiều instance có thể cùng khởi động. [Cloud Run jobs](https://docs.cloud.google.com/sdk/gcloud/reference/run/jobs/deploy).

```bash
gcloud run deploy fastapi-blog \
  --image "$APP_IMAGE" --region "$APP_REGION" \
  --service-account "$APP_SERVICE_ACCOUNT" \
  --port 8080 --allow-unauthenticated \
  --no-cpu-throttling \
  --set-env-vars 'FORWARDED_ALLOW_IPS=*,FRONTEND_URL=https://blog.example.com,S3_BUCKET_NAME=your-bucket,S3_REGION=us-east-1,MAIL_SERVER=smtp.example.com,MAIL_PORT=587,MAIL_USERNAME=your-smtp-user,MAIL_FROM=noreply@example.com,MAIL_USE_TLS=true' \
  --set-secrets SECRET_KEY=blog-secret-key:1,DATABASE_URL=blog-database-url:1,S3_ACCESS_KEY_ID=blog-s3-access-key:1,S3_SECRET_ACCESS_KEY=blog-s3-secret-key:1,MAIL_PASSWORD=blog-mail-password:1
```

Ví dụ mở blog công khai; các API ghi dữ liệu vẫn kiểm tra JWT. Đặt `FRONTEND_URL`
thành URL HTTPS thực tế trước khi dùng chức năng quên mật khẩu. Tùy tải, cấu hình
giới hạn instance/concurrency phù hợp số kết nối PostgreSQL cho phép.

Email hiện dùng FastAPI BackgroundTasks. `--no-cpu-throttling` cho phép CPU ngoài
thời gian xử lý request, nhưng không biến tác vụ thành hàng đợi bền vững: instance
vẫn có thể bị dừng. Nếu cần bảo đảm gửi email/retry, dùng hàng đợi ngoài ứng dụng.

Sau deploy, kiểm tra `/health`, trang chủ, đăng nhập, upload S3 và email reset.
`/health` chỉ kiểm tra database. HSTS được gửi trên HTTPS, ngoại trừ localhost;
`includeSubDomains` yêu cầu các subdomain liên quan cũng sử dụng HTTPS.

Nguồn code: [Part 19, commit 75e404d](https://github.com/CoreyMSchafer/FastAPI-19-Deployment-Docker-GCR/commit/75e404d1dfe31b0ac6cb74e492de986183a51955).
Tham khảo [uv trong Docker](https://docs.astral.sh/uv/guides/integration/docker/).
