"""MinIO (S3 uyumlu) dosya yükleme yardımcısı."""
import os
import uuid
import logging
import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

S3_ENDPOINT = os.environ.get('S3_ENDPOINT', 'http://10.0.0.3:9000')
S3_KEY = os.environ.get('S3_ACCESS_KEY', 'emlakasistan_minio')
S3_SECRET = os.environ.get('S3_SECRET_KEY', 'Min10Str0ngKey2026Sec')
S3_BUCKET = os.environ.get('S3_BUCKET', 'tarim')
S3_PUBLIC_BASE = os.environ.get('S3_PUBLIC_BASE', '')  # reverse proxy varsa

_CLIENT = None


def _client():
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = boto3.client(
            's3',
            endpoint_url=S3_ENDPOINT,
            aws_access_key_id=S3_KEY,
            aws_secret_access_key=S3_SECRET,
            config=Config(signature_version='s3v4'),
            region_name='us-east-1',
        )
    return _CLIENT


ALLOWED_MIMES = {
    'image/jpeg', 'image/jpg', 'image/png', 'image/webp',
    'image/heic', 'image/gif',
    'application/pdf',
}


def put_photo(file_storage, parent_type, parent_id):
    """Flask FileStorage objesi → MinIO'ya yükle, (s3_key, mime) döner."""
    mime = (file_storage.mimetype or '').lower()
    if mime not in ALLOWED_MIMES:
        raise ValueError(f'Desteklenmeyen tür: {mime}')

    ext = os.path.splitext(file_storage.filename or '')[1].lower()[:6] or '.bin'
    key = f'{parent_type}/{parent_id}/{uuid.uuid4().hex}{ext}'
    file_storage.stream.seek(0)
    _client().upload_fileobj(
        file_storage.stream,
        S3_BUCKET,
        key,
        ExtraArgs={'ContentType': mime},
    )
    return key, mime


def presigned_get(s3_key, seconds=3600):
    """Kısa ömürlü indirme URL'i üret."""
    try:
        return _client().generate_presigned_url(
            'get_object',
            Params={'Bucket': S3_BUCKET, 'Key': s3_key},
            ExpiresIn=seconds,
        )
    except ClientError as e:
        logger.exception(f'presigned_get hatası: {e}')
        return None


def delete_photo(s3_key):
    try:
        _client().delete_object(Bucket=S3_BUCKET, Key=s3_key)
        return True
    except ClientError as e:
        logger.exception(f'delete_photo hatası: {e}')
        return False


def get_bytes(s3_key):
    """Foto içeriğini bytes olarak döner (AI vision için)."""
    try:
        resp = _client().get_object(Bucket=S3_BUCKET, Key=s3_key)
        return resp['Body'].read()
    except ClientError as e:
        logger.exception(f'get_bytes hatası: {e}')
        return None
