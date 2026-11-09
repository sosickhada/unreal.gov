"""Private raster ingestion. Preserve original bytes; explicit crop, never stretch."""
from io import BytesIO
from pathlib import Path
import hashlib
from PIL import Image, ImageOps
from .images import inspect_image


def ingest(data, destination):
    if len(data)>20_000_000: raise ValueError('Image exceeds 20MB')
    with Image.open(BytesIO(data)) as im:
        if im.format not in ('JPEG','PNG','WEBP') or getattr(im,'n_frames',1)!=1: raise ValueError('Static JPEG/PNG/WebP required')
        if im.width*im.height>40_000_000 or min(im.size)<512: raise ValueError('Image dimensions outside safe range')
        original_size=im.size
        im=ImageOps.exif_transpose(im).convert('RGB')
        fitted=ImageOps.fit(im,(1080,1350),method=Image.Resampling.LANCZOS,centering=(.5,.4))
        buf=BytesIO();fitted.save(buf,'PNG')
    metadata=inspect_image(buf.getvalue())
    path=Path(destination).resolve();path.parent.mkdir(parents=True,exist_ok=True)
    original=path.with_suffix('.original')
    if path.exists() and (path.read_bytes()!=buf.getvalue() or not original.is_file() or original.read_bytes()!=data):raise ValueError('Existing immutable asset conflicts')
    original.write_bytes(data);original.chmod(0o600)
    temp=path.with_suffix('.pending');temp.write_bytes(buf.getvalue());temp.chmod(0o600);temp.replace(path)
    return dict(metadata,path=str(path),original_path=str(original),original_sha256=hashlib.sha256(data).hexdigest(),original_width=original_size[0],original_height=original_size[1],transform='4:5 crop; Lanczos resize; no stretching',upscaled=original_size[0]<1080 or original_size[1]<1350)


def fetch_generated(url):
    import ipaddress, socket, requests
    from urllib.parse import urlparse
    parsed=urlparse(url);host=parsed.hostname or ''
    if parsed.scheme!='https' or parsed.username or parsed.password or parsed.port not in (None,443):raise ValueError('Untrusted generated URL')
    allowed=('puter.com','puterusercontent.com','replicate.delivery','bfl.ai','oaistatic.com')
    if not any(host==h or host.endswith('.'+h) for h in allowed):raise ValueError('Generated image host not approved')
    addresses=socket.getaddrinfo(host,443,type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):raise ValueError('Non-public generated image address')
    with requests.get(url,timeout=30,stream=True,allow_redirects=False) as response:
        if response.status_code!=200:raise ValueError('Generated image download failed')
        data=bytearray()
        for chunk in response.iter_content(65536):
            data.extend(chunk)
            if len(data)>20_000_000:raise ValueError('Image too large')
    return bytes(data)
