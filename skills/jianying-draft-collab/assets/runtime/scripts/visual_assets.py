"""Local provenance audit for image-generated teaching assets. No network or writes."""
from pathlib import Path
from urllib.parse import urlparse
import hashlib
import json

QA_FIELDS = ('facts', 'text', 'visual')

def require(condition, message):
    if not condition:
        raise ValueError(message)

def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))

def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

def local_file(root, spec, label):
    require(isinstance(spec, dict), label + ': file record required')
    path = spec.get('path')
    require(isinstance(path, str) and path, label + ': relative path required')
    relative = Path(path)
    require(not relative.is_absolute(), label + ': path must be project-relative')
    resolved = (root / relative).resolve()
    require(resolved.is_relative_to(root), label + ': path leaves project')
    require(resolved.is_file(), label + ': file missing')
    expected = spec.get('sha256')
    require(isinstance(expected, str) and len(expected) == 64, label + ': SHA256 required')
    require(digest(resolved) == expected.lower(), label + ': SHA256 mismatch')
    return resolved

def consumed_interval(row, source, fps):
    start = row.get('source_start_us', 0)
    duration = round(row['frames'] / fps * 1000000 * row.get('speed', 1))
    return start, min(row.get('source_end_us', source['duration_us']), start + duration)

def audit_images(project, plan=None, sources=None, images_only=False):
    root = Path(project).resolve()
    plan = read_json(root / 'production-plan.json') if plan is None else plan
    sources = read_json(root / 'sources.json') if sources is None else sources
    if isinstance(sources, list):
        sources = {row['id']: row for row in sources}
    manifest_path = plan.get('visual_asset_manifest')
    require(isinstance(manifest_path, str) and manifest_path,
            'visual_asset_manifest required for new builds; legacy validate remains available')
    manifest_file = root / manifest_path
    require(not Path(manifest_path).is_absolute() and manifest_file.resolve().is_relative_to(root),
            'visual_asset_manifest must stay within project')
    require(manifest_file.is_file(), 'visual_asset_manifest file missing')
    manifest = read_json(manifest_file)
    require(manifest.get('version') == 1, 'Unsupported visual asset manifest version')
    assets = manifest.get('assets')
    require(isinstance(assets, list), 'Manifest assets must be an array')
    rows = {row['id']: row for row in plan['segments']}
    images = plan.get('images', {})
    reviews = manifest.get('source_reviews')
    require(isinstance(reviews, dict), 'source_reviews required, including captures and derived videos')
    used_sources = {row['source_id'] for row in rows.values() if row.get('source_id')}
    checked_sources = set()
    deferred_sources = set()
    def check_source(source_id):
        if source_id in checked_sources:
            return
        if images_only and reviews.get(source_id, {}).get('kind') == 'derived_video':
            deferred_sources.add(source_id)
            return
        source = sources[source_id]
        source_path = Path(source.get('path', ''))
        require(source_path.is_file(), source_id + ': source file missing')
        require(digest(source_path) == source.get('sha256'), source_id + ': source SHA256 mismatch')
        checked_sources.add(source_id)
    for source_id in used_sources:
        require(source_id in sources, source_id + ': source record missing')
        check_source(source_id)
    require(used_sources <= set(reviews), 'Missing source review: ' + ', '.join(sorted(used_sources - set(reviews))))
    require(set(reviews) <= set(sources), 'Source review references unknown source')
    declared_static = set()
    for source_id, review in reviews.items():
        require(isinstance(review, dict), source_id + ': invalid source review')
        require(review.get('kind') in ('capture', 'derived_video'), source_id + ': unknown source review kind')
        ranges = review.get('static_ranges', [])
        require(isinstance(ranges, list), source_id + ': static_ranges must be an array')
        require(review['kind'] != 'capture' or not ranges, source_id + ': capture cannot contain authored static pages')
        for interval in ranges:
            image_id = interval.get('image_id')
            start, end = interval.get('start_us'), interval.get('end_us')
            require(isinstance(image_id, str) and image_id, source_id + ': static image_id required')
            require(type(start) is int and type(end) is int and 0 <= start < end <= sources[source_id]['duration_us'],
                    source_id + ': invalid static source interval')
            for row in rows.values():
                if row.get('source_id') != source_id:
                    continue
                consumed_start, consumed_end = consumed_interval(row, sources[source_id], plan.get('fps', 60))
                intersection_start, intersection_end = max(start, consumed_start), min(end, consumed_end)
                if intersection_start < intersection_end:
                    declared_static.add((row['id'], source_id, image_id, intersection_start, intersection_end))
    ids, image_coverage, used_static, counts = set(), set(), set(), {'generated': 0, 'evidence_capture': 0}
    for asset in assets:
        image_id = asset.get('image_id')
        require(isinstance(image_id, str) and image_id and image_id not in ids, 'Unique image_id required')
        ids.add(image_id)
        label = image_id
        require(all(asset.get('qa', {}).get(field) == 'passed' for field in QA_FIELDS), label + ': QA incomplete')
        original = local_file(root, asset.get('original'), label + ' original')
        from PIL import Image
        with Image.open(original) as im:
            require(im.format in ('PNG', 'JPEG', 'WEBP'), label + ': expected downloaded raster original')
            im.verify()
        kind = asset.get('kind', 'generated')
        require(kind in counts, label + ': unknown asset kind')
        counts[kind] += 1
        if kind == 'generated':
            require(asset.get('lane') == 'web_chatgpt_chrome' and asset.get('mode') == 'create_image',
                    label + ': generated assets must use Chrome ChatGPT Create image')
            url = urlparse(asset.get('conversation_url', ''))
            require(url.scheme == 'https' and url.netloc in ('chatgpt.com', 'chat.openai.com')
                    and '/c/' in url.path and not url.path.endswith('/c/') and 'local-chatgpt' not in url.path,
                    label + ': completed ChatGPT conversation URL required')
            prompt = local_file(root, asset.get('prompt'), label + ' prompt')
            require(bool(prompt.read_text(encoding='utf-8-sig').strip()), label + ': empty prompt')
        else:
            require(asset.get('lane') == 'source_evidence' and asset.get('mode') == 'capture',
                    label + ': evidence must be an unredrawn source capture')
            evidence = asset.get('evidence', {})
            source_id = evidence.get('source_id')
            source_file = evidence.get('source_file')
            require((source_id is not None) != (source_file is not None), label + ': choose video-frame or standalone-image evidence')
            if source_id is not None:
                require(source_id in sources, label + ': evidence source_id required')
                check_source(source_id)
                require(evidence.get('source_sha256') == sources[source_id]['sha256'], label + ': evidence source SHA mismatch')
                at = evidence.get('at_us')
                require(type(at) is int and 0 <= at < sources[source_id]['duration_us'], label + ': invalid evidence timestamp')
            else:
                source_image = local_file(root, source_file, label + ' evidence source image')
                box = evidence.get('crop_box')
                if box is None:
                    require(digest(original) == source_file['sha256'].lower(), label + ': standalone evidence must retain original bytes')
                else:
                    require(isinstance(box, list) and len(box) == 4 and all(type(v) is int for v in box),
                            label + ': crop_box must contain four integer pixel bounds')
                    with Image.open(source_image) as source_im, Image.open(original) as adopted_im:
                        require(0 <= box[0] < box[2] <= source_im.width and 0 <= box[1] < box[3] <= source_im.height,
                                label + ': crop_box outside source image')
                        expected = source_im.crop(tuple(box)).convert('RGBA')
                        actual = adopted_im.convert('RGBA')
                        require(expected.size == actual.size and expected.tobytes() == actual.tobytes(),
                                label + ': evidence crop must preserve source pixels')
        if image_id in images:
            planned = images[image_id]
            local_file(root, planned, label + ' planned image')
            require(planned['sha256'].lower() == asset['original']['sha256'].lower(),
                    label + ': use the downloaded original; adapt during video rendering')
        usages = asset.get('usage')
        require(isinstance(usages, list) and usages, label + ': usage required')
        for usage in usages:
            usage_type = usage.get('type')
            if usage_type == 'cover':
                cover = local_file(root, usage.get('file'), label + ' cover')
                require(digest(cover) == asset['original']['sha256'].lower(), label + ': cover differs from original')
                continue
            segment_id = usage.get('segment_id')
            require(segment_id in rows, label + ': unknown segment_id')
            row = rows[segment_id]
            if usage_type == 'image':
                require(row.get('image_id') == image_id, label + ': image usage does not match segment')
                image_coverage.add((segment_id, image_id))
            elif usage_type == 'derived_video_static':
                source_id = usage.get('source_id')
                start, end = usage.get('start_us'), usage.get('end_us')
                require(row.get('source_id') == source_id and source_id in sources,
                        label + ': derived usage does not match source segment')
                require(reviews[source_id]['kind'] == 'derived_video', label + ': derived source review required')
                source_start, source_end = consumed_interval(row, sources[source_id], plan.get('fps', 60))
                require(type(start) is int and type(end) is int and source_start <= start < end <= source_end,
                        label + ': static interval outside consumed source range')
                used_static.add((segment_id, source_id, image_id, start, end))
            else:
                raise ValueError(label + ': unknown usage type')
    expected_images = {(row['id'], row['image_id']) for row in rows.values() if row.get('image_id')}
    require(expected_images <= image_coverage, 'Image segments missing provenance usage')
    require(set(images) <= ids, 'Planned image missing provenance asset')
    require(declared_static == used_static, 'Derived static intervals and asset usage must match')
    return {'status': 'images_ready' if images_only else 'passed', 'manifest': manifest_path, 'assets': len(assets),
            'generated_assets': counts['generated'], 'evidence_captures': counts['evidence_capture'],
            'image_segments': len(expected_images), 'reviewed_video_sources': len(used_sources),
            'derived_static_intervals': len(used_static), 'deferred_video_sources': sorted(deferred_sources),
            'verification_scope': 'local files, hashes, declared provenance and coverage; webpage truth is reviewed by the browser controller'}
