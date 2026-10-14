# Prepared context is emitted only after all pinned payload signatures verify.
ARG BASE_IMAGE=registry.access.redhat.com/ubi9/ubi-minimal@sha256:34880b64c07f28f64d95737f82f891516de9a3b43583f39970f7bf8e4cfa48b7
FROM ${BASE_IMAGE} AS common
ARG TARGETARCH
COPY bin/${TARGETARCH}/mc /usr/bin/mc
COPY contracts/mc_license /licenses/mc/LICENSE
COPY contracts/mc_credits /licenses/mc/CREDITS
ENV MC_CONFIG_DIR=/tmp/.mc

FROM common AS minio
ARG TARGETARCH
COPY bin/${TARGETARCH}/minio /usr/bin/minio
COPY contracts/entrypoint /usr/bin/docker-entrypoint.sh
COPY contracts/minio_license /licenses/minio/LICENSE
COPY contracts/minio_credits /licenses/minio/CREDITS
RUN chmod 0555 /usr/bin/docker-entrypoint.sh
ENV MINIO_ACCESS_KEY_FILE=access_key \
    MINIO_SECRET_KEY_FILE=secret_key \
    MINIO_ROOT_USER_FILE=access_key \
    MINIO_ROOT_PASSWORD_FILE=secret_key \
    MINIO_KMS_SECRET_KEY_FILE=kms_master_key \
    MINIO_UPDATE_MINISIGN_PUBKEY=RWTx5Zr1tiHQLwG9keckT0c45M3AGeHD6IvimQHpyRywVWGbP1aVSGav \
    MINIO_CONFIG_ENV_FILE=config.env
EXPOSE 9000 9001
VOLUME ["/data"]
ENTRYPOINT ["/usr/bin/docker-entrypoint.sh"]
CMD ["minio"]

FROM common AS minio-client
ENTRYPOINT ["/usr/bin/mc"]
