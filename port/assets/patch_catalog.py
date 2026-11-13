"""Make the Windows copy of the Addressables catalog load the (already decrypted) bundles with the stock provider.

    python patch_catalog.py <aa_win/catalog.json>

The game's own EncryptedAssetBundleProvider decrypts 145 bundles at load; retarget_all.py writes those bundles
decrypted, so their provider id is replaced by the stock AssetBundleProvider. Bundle CRCs are already 0 in this
catalog, so rewritten bundles need no other change.
"""
import sys, json

p = sys.argv[1]
c = json.load(open(p, encoding='utf-8'))
ENC = 'GCS1.AddressableAssetEncryption.EncryptedAssetBundleProvider'
STOCK = 'UnityEngine.ResourceManagement.ResourceProviders.AssetBundleProvider'
n = 0
for i, s in enumerate(c['m_ProviderIds']):
    if s == ENC:
        c['m_ProviderIds'][i] = STOCK
        n += 1
json.dump(c, open(p, 'w', encoding='utf-8'), separators=(',', ':'), ensure_ascii=False)
print('provider ids replaced:', n, c['m_ProviderIds'])
