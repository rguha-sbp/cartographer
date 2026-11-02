Parity goldens: curated diagrams and the `.drawio` files that they must render to. They show that a refactor does not change the output.
To regenerate a pair, run `tf_layout.layout` on the curated JSON. Then run `gen_drawio.render(..., page_id="golden", page_name="golden")`.
