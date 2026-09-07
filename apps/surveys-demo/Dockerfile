FROM docker.io/oven/bun:1.2.19-alpine@sha256:7dc0e33a62cbc1606d14b07706c3a00ae66e8e9d0e81b83241ed609763e66d55 AS packed
WORKDIR /package
COPY packages/surveys ./
RUN mkdir /artifact && bun pm pack --ignore-scripts --filename /artifact/surveys.tgz

FROM docker.io/oven/bun:1.2.19-alpine@sha256:7dc0e33a62cbc1606d14b07706c3a00ae66e8e9d0e81b83241ed609763e66d55 AS consumer
WORKDIR /consumer
COPY --from=packed /artifact /artifact
COPY apps/surveys-demo/package.template.json ./package.json
COPY apps/surveys-demo/consumer.lock ./bun.lock
RUN bun install --frozen-lockfile --ignore-scripts
COPY apps/surveys-demo/client.tsx apps/surveys-demo/exports.tsx apps/surveys-demo/host.css apps/surveys-demo/server.mjs apps/surveys-demo/inspect.mjs ./
RUN bun build client.tsx --target=browser --outdir=dist --sourcemap=external --define process.env.NODE_ENV='"production"'
RUN bun build exports.tsx --target=browser --outdir=dist --sourcemap=external --define process.env.NODE_ENV='"production"'
RUN bun inspect.mjs
RUN mkdir /data && chown bun:bun /data
USER bun
CMD ["bun", "server.mjs"]
