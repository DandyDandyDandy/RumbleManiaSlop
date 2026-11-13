"""Decrypt GCS1.AddressableAssetEncryption bundles (EncryptedAssetBundleProvider / AesEncryptor).

Scheme (recovered from main.bin, AesEncryptor.<Decrypt>d__2::MoveNext and
EncryptedAssetBundleResource.<LoadLocalBundleAsync>d__13::MoveNext):
    password = Path.GetFileNameWithoutExtension(bundle path)        (the 32-hex-char file name)
    key      = new PasswordDeriveBytes(password, new byte[16]).GetBytes(aes.KeySize / 8)
               -> PBKDF1-SHA1, 100 iterations, MS/Mono extension to 32 bytes, salt = 16 zero bytes
    iv       = AesEncryptor.InitialVector = 00 01 02 ... 0f
    AES-256-CBC, PKCS7 padding, whole file.

    python decrypt_bundle.py <in.bundle> <out.bundle>
    python decrypt_bundle.py --all <Switch dir> <out dir>     decrypt every non-UnityFS *.bundle in the dir root
"""
import hashlib, os, sys
from Crypto.Cipher import AES

IV = bytes(range(16))


def password_derive_bytes(password: bytes, salt: bytes, n: int, iterations: int = 100) -> bytes:
    base = hashlib.sha1(password + salt).digest()
    for _ in range(iterations - 2):
        base = hashlib.sha1(base).digest()
    out = hashlib.sha1(base).digest()
    counter = 1
    while len(out) < n:
        out += hashlib.sha1(str(counter).encode() + base).digest()
        counter += 1
    return out[:n]


def decrypt(data: bytes, name: str) -> bytes:
    key = password_derive_bytes(name.encode('utf-8'), bytes(16), 32)
    pt = AES.new(key, AES.MODE_CBC, IV).decrypt(data)
    pad = pt[-1]
    if not 1 <= pad <= 16 or pt[-pad:] != bytes([pad]) * pad:
        raise ValueError('bad PKCS7 padding (wrong key/name?)')
    return pt[:-pad]


def decrypt_file(src, dst):
    name = os.path.splitext(os.path.basename(src))[0]
    pt = decrypt(open(src, 'rb').read(), name)
    if pt[:8] != b'UnityFS\0':
        raise ValueError(f'{src}: decrypted data is not UnityFS')
    with open(dst, 'wb') as f:
        f.write(pt)
    return len(pt)


if __name__ == '__main__':
    if sys.argv[1] == '--all':
        src, dst = sys.argv[2], sys.argv[3]
        os.makedirs(dst, exist_ok=True)
        n = 0
        for fn in sorted(os.listdir(src)):
            p = os.path.join(src, fn)
            if fn.endswith('.bundle') and os.path.isfile(p):
                with open(p, 'rb') as f:
                    if f.read(7) == b'UnityFS':
                        continue
                decrypt_file(p, os.path.join(dst, fn))
                n += 1
        print('decrypted', n, 'bundles ->', dst)
    else:
        print(decrypt_file(sys.argv[1], sys.argv[2]), 'bytes')
