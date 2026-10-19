ARG STATIC_IMAGE=cgr.dev/chainguard/static:latest
ARG BUILD_JOBS=8

FROM cgr.dev/chainguard/wolfi-base:latest AS build

ARG ASIO_TAG=asio-1-38-2
ARG ASIO_COMMIT=12b52a54a25d1861b037bc5d9810f92a7151d920
ARG CROW_TAG=v1.3.4
ARG CROW_COMMIT=cfe92bb464cdc7ca08b403d8782ee8de99df3722

RUN apk add --no-cache \
        build-base \
        cmake \
        git \
        ninja-build

ENV PATH=/usr/lib/ninja-build/bin:${PATH}
RUN ninja --version

RUN git clone --branch "${ASIO_TAG}" --depth 1 https://github.com/chriskohlhoff/asio.git /tmp/asio \
    && test "$(git -C /tmp/asio rev-parse HEAD)" = "${ASIO_COMMIT}" \
    && cp -r /tmp/asio/asio/include/asio.hpp /tmp/asio/asio/include/asio /usr/local/include/ \
    && rm -rf /tmp/asio

ARG BUILD_JOBS

RUN git clone --branch "${CROW_TAG}" --depth 1 https://github.com/CrowCpp/Crow.git /tmp/crow \
    && test "$(git -C /tmp/crow rev-parse HEAD)" = "${CROW_COMMIT}" \
    && cmake -S /tmp/crow -B /tmp/crow/build -GNinja \
        -DCMAKE_BUILD_TYPE=Release \
        -DCROW_BUILD_EXAMPLES=OFF \
        -DCROW_BUILD_TESTS=OFF \
    && cmake --build /tmp/crow/build --parallel "${BUILD_JOBS}" \
    && cmake --install /tmp/crow/build \
    && rm -rf /tmp/crow

WORKDIR /src

COPY CMakeLists.txt mcp.cc ./

RUN cmake -S . -B build -GNinja -DCMAKE_BUILD_TYPE=Release -DCMAKE_CXX_STANDARD=26 \
    && cmake --build build --parallel "${BUILD_JOBS}"

RUN mkdir -p /out/usr/local/bin \
    && cp build/mcp /out/usr/local/bin/mcp \
    && loader="$(find /usr/lib /lib -maxdepth 1 -name 'ld-linux-*.so.*' | head -n1)" \
    && for bin in /out/usr/local/bin/*; do \
         "$loader" --list "$bin" 2>/dev/null; \
       done \
       | sed -nE 's#^[[:space:]]*([^[:space:]]+)[[:space:]]=>[[:space:]]*(/[^[:space:]]+).*#\1|\2#p; s#^[[:space:]]*(/[^[:space:]]+)[[:space:]].*#\1|\1#p' \
       | sort -u > /tmp/libs.txt \
    && while IFS='|' read -r name path; do \
         real="$(realpath "$path")" \
         && mkdir -p "/out$(dirname "$real")" \
         && cp -Lf "$real" "/out$real" \
         && base="$(basename "$name")" \
         && [ "$base" = "$(basename "$real")" ] \
         || ln -sf "$(basename "$real")" "/out$(dirname "$real")/$base"; \
       done < /tmp/libs.txt \
    && cp -L "$loader" "/out$loader"

FROM ${STATIC_IMAGE}

COPY --from=build /out/ /

WORKDIR /app

ENV MCP_BIND=0.0.0.0 \
    MCP_PORT=8080

USER 65532:65532

EXPOSE 8080

ENTRYPOINT ["/usr/local/bin/mcp"]
