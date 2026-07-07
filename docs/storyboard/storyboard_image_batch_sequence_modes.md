# Storyboard Image Batch Sequence Modes

`auto-generate-missing-images` creates an orchestration batch for missing storyboard frame images. The orchestration batch controls ordering and dependencies, while each ready item still calls the existing `generate_image()` path. Auth and computing-power deduction therefore remain on the same path as manual frontend generation.

## Modes

- `speed`: submit all missing images up to `limit` without previous-frame references.
- `balanced`: default. Submit the first ready scene in each parsed group concurrently. Later scenes in the same group wait for the previous scene result and submit through `image_edit` with that result as `source_image`.
- `quality`: submit one global chain. Every scene waits for the previous scene, even across group boundaries.

Inserted scenes without parsed group metadata inherit the previous scene's group. If the first scene has no group metadata, it uses a temporary manual group.

Existing completed scenes participate in dependencies. If A1 already has a first frame and A2 is missing, A2 references A1 without regenerating A1. Existing running scenes also participate; dependent scenes wait until the selected asset has a result URL.

When a dependent scene uses the previous scene image, that previous image is appended after the scene's described reference images. This keeps prompt legends aligned: if the prompt says Image #1 is a character and Image #2 is a location, those images remain at the front of the image-edit queue, while the previous storyboard frame is an extra continuity reference at the tail. The previous-frame item is also described in the reference legend as `图N是前一分镜。` (no name after the colon), so the legend image numbers stay strictly aligned with the image-edit URL queue. If the previous-frame URL coincides with an existing role/prop/location reference, it is de-duplicated and not described twice.

## CLI

```bash
python -m scripts.storyboard_agent_cli auto-generate-missing-images \
  --storyboard-id 10 \
  --user-id 1 \
  --auth-token "<auth_token>" \
  --asset-type first_frame \
  --limit 5 \
  --sequence-mode balanced
```

The command returns `batch_id`. Query it with:

```bash
python -m scripts.storyboard_agent_cli storyboard-image-batch-status \
  --batch-id <batch_id> \
  --user-id 1
```

## HTTP

```bash
curl -X POST "$BASE_URL/api/storyboard/10/auto-generate-missing-images" \
  -H "Authorization: Bearer <auth_token>" \
  -H "Content-Type: application/json" \
  -d '{"asset_type":"first_frame","mode":"auto","limit":5,"sequence_mode":"balanced"}'
```

```bash
curl "$BASE_URL/api/storyboard/image-batches/<batch_id>/status" \
  -H "Authorization: Bearer <auth_token>"
```

The response status includes `pending`, `running`, `completed`, `failed`, and `partial`.
