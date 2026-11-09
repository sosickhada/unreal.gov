"""Optional local-only image fallback. Never routes to a billable cloud API."""
from pathlib import Path
import json
from .content import safe_https
from .images import inspect_image


def scene_prompt(draft,slot):
    scene=draft.get('image_queries',{}).get(slot,'')
    brief=draft.get('image_brief',{}).get(slot,{})
    if isinstance(brief,dict): scene+='; '+ '; '.join(str(brief.get(k,''))[:160] for k in ('persons','place','situation','emotion','composition'))
    return ('Documentary photograph, natural window light, realistic matte materials, restrained colors. '
            'Vertical 4:5, main subject in upper two thirds, dark quiet lower third for later layout. '
            'Scene: '+scene+'. No captions, no typography, no signs, no logos, no watermark, '
            'no HDR, no glossy plastic skin, no distorted hands or faces. No identifiable people.')


def generate_local(config,draft,slot,destination):
    # A fixed local pipeline avoids cloud credentials, endpoints and accidental billing.
    model=config.env.get('LOCAL_IMAGE_MODEL_DIR','')
    if not model or not Path(model).is_dir():
        return {'available':False,'reason':'No verified free hosted API configured; local model not installed','prompt':scene_prompt(draft,slot)}
    source=config.env.get('LOCAL_IMAGE_MODEL_SOURCE_URL','')
    license_url=config.env.get('LOCAL_IMAGE_MODEL_LICENSE_URL','')
    license_name=config.env.get('LOCAL_IMAGE_MODEL_LICENSE','')
    if not safe_https(source) or not safe_https(license_url) or not license_name:
        return {'available':False,'reason':'Local model commercial license evidence required','prompt':scene_prompt(draft,slot)}
    config.require_external()
    from diffusers import AutoPipelineForText2Image
    import torch
    pipeline=AutoPipelineForText2Image.from_pretrained(model,local_files_only=True,torch_dtype=torch.float32)
    image=pipeline(prompt=scene_prompt(draft,slot),negative_prompt='text, watermark, HDR, distorted anatomy, wax skin',width=1080,height=1352,num_inference_steps=25).images[0]
    image=image.crop((0,0,1080,1350));path=Path(destination);path.parent.mkdir(parents=True,exist_ok=True);image.save(path)
    evidence=inspect_image(path.read_bytes())
    return dict(evidence,available=True,path=str(path),provider='local-diffusers',ai_generated=True,
                prompt=scene_prompt(draft,slot),review_required=True,license_review_required=True,
                model_path=model,license_verified=False,source_url=source,license_url=license_url,license=license_name)
