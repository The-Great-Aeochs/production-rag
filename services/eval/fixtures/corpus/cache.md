# Response cache
The exact response cache preserves query case. Cache keys include token owner, corpus filter, source filters, top_k, model names, prompt version, generation settings, and the corpus revision. Conversation answers are not cached. Cache hits skip embedding. Every document publication and deletion advances the corpus revision.
