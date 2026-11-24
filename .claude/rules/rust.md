# Rust Rules

## Toolchain

The project pins `nightly-2025-12-05` in `rust-toolchain`. Always use `uv run cargo` to invoke it.

If `uv` is unavailable or locked, invoke nightly explicitly:
```sh
PROTOC=/mnt/data_infra/workspace/monarch/target/protoc/bin/protoc \
  RUSTC=~/.rustup/toolchains/nightly-2025-12-05-x86_64-unknown-linux-gnu/bin/rustc \
  ~/.rustup/toolchains/nightly-2025-12-05-x86_64-unknown-linux-gnu/bin/cargo <cmd>
```

NEVER use the bare `cargo` command — Spack installs a 1.92.0 stable `cargo` earlier in `$PATH` that will fail on nightly-only features.

## protoc

`tracing-perfetto-sdk-schema` requires protobuf compiler. It is pre-built at:
```
/mnt/data_infra/workspace/monarch/target/protoc/bin/protoc
```

Set `PROTOC` to this path for any direct cargo invocation. `uv run cargo` sets it automatically.

## Style

- Edition 2024 (`rustfmt.toml`): `imports_granularity = "Item"`, `group_imports = "StdExternalCrate"`
- `snake_case` for functions/vars, `CamelCase` for types/traits
- Run `cargo fmt` before finalizing any Rust edit

## Actor Pattern

```rust
#[derive(Handler, HandleClient, RefClient, Debug, Serialize, Deserialize, Named)]
enum MyMsg {
    Fire(String),                                     // one-way
    Query(#[reply] reference::OncePortRef<u64>),      // RPC
}

impl Actor for MyActor {}

#[async_trait]
#[hyperactor::handle(MyMsg)]
impl MyMsgHandler for MyActor {
    async fn fire(&mut self, cx: &Context<Self>, arg0: String) -> Result<()> { ... }
    async fn query(&mut self, cx: &Context<Self>) -> Result<u64, anyhow::Error> { ... }
}
```

- Unnamed tuple variant fields are named `arg0`, `arg1` in the generated trait
- `#[reply]` must be on the last field of an enum variant
- `Proc` must be `let mut proc` if `destroy_and_wait` is called
