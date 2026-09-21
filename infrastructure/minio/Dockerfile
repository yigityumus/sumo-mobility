FROM golang:1.24.8-alpine AS builder

ARG MINIO_VERSION=RELEASE.2025-10-15T17-29-55Z

RUN CGO_ENABLED=0 go install "github.com/minio/minio@${MINIO_VERSION}" \
    && rm -rf /go/pkg/mod /root/.cache/go-build


FROM alpine:3.22

RUN apk add --no-cache ca-certificates curl

COPY --from=builder /go/bin/minio /usr/local/bin/minio

VOLUME ["/data"]
EXPOSE 9000 9001

ENTRYPOINT ["minio"]
CMD ["server", "/data", "--console-address", ":9001"]
