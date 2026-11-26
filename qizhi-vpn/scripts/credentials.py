"""Local credential storage; Windows DPAPI, macOS Keychain, Linux system keyring."""
import argparse
import ctypes
import getpass
import json
import os
from pathlib import Path
import platform
import subprocess
import sys

SERVICE = 'qizhi-vpn.sii.edu.cn'
ACCOUNT = 'default'


def state_dir():
    if os.environ.get('QIZHI_VPN_STATE_DIR'):
        return Path(os.environ['QIZHI_VPN_STATE_DIR']).expanduser().resolve()
    if sys.platform == 'win32':
        return Path(os.environ['LOCALAPPDATA']) / 'QizhiVPN'
    if sys.platform == 'darwin':
        return Path.home() / 'Library' / 'Application Support' / 'QizhiVPN'
    return Path(os.environ.get('XDG_STATE_HOME', str(Path.home() / '.local' / 'state'))) / 'qizhi-vpn'


def private_dir(path):
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if sys.platform == 'win32':
        import csv
        raw = subprocess.check_output(['whoami', '/user', '/fo', 'csv', '/nh'], text=True)
        sid = next(csv.reader([raw.strip()]))[-1]
        # Replace the DACL: /grant:r alone can leave explicit broad grants behind.
        literal = str(path.resolve()).replace("'", "''")
        script = """
$ErrorActionPreference = 'Stop'
$acl = [System.Security.AccessControl.DirectorySecurity]::new()
$acl.SetAccessRuleProtection($true, $false)
foreach ($sid in @('%s', 'S-1-5-18')) {
    $identity = [System.Security.Principal.SecurityIdentifier]::new($sid)
    $rule = [System.Security.AccessControl.FileSystemAccessRule]::new(
        $identity, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow')
    $acl.AddAccessRule($rule)
}
[System.IO.Directory]::SetAccessControl('%s', $acl)
""" % (sid, literal)
        import base64
        encoded = base64.b64encode(script.encode('utf-16-le')).decode('ascii')
        result = subprocess.run(['powershell.exe', '-NoProfile', '-EncodedCommand', encoded],
                                capture_output=True)
        if result.returncode:
            raise RuntimeError('Cannot restrict the credential directory permissions; storage was not attempted.')
    else:
        path.chmod(0o700)


def dpapi(data, decrypt=False):
    from ctypes import wintypes
    class Blob(ctypes.Structure):
        _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_ubyte))]
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    backing = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(backing, ctypes.POINTER(ctypes.c_ubyte)))
    output = Blob()
    if decrypt:
        fn = crypt.CryptUnprotectData
        fn.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                       ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
        second = None
    else:
        fn = crypt.CryptProtectData
        fn.argtypes = [ctypes.POINTER(Blob), wintypes.LPCWSTR, ctypes.c_void_p,
                       ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
        second = SERVICE
    fn.restype = wintypes.BOOL
    if not fn(ctypes.byref(source), second, None, None, None, 1, ctypes.byref(output)):
        raise RuntimeError('Windows DPAPI operation failed for the current user.')
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        kernel.LocalFree.restype = ctypes.c_void_p
        kernel.LocalFree(output.pbData)


def mac_keychain(data=None):
    """Security.framework avoids putting a password in process arguments."""
    sec = ctypes.CDLL('/System/Library/Frameworks/Security.framework/Security')
    cf = ctypes.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
    u32, ptr = ctypes.c_uint32, ctypes.c_void_p
    sec.SecKeychainFindGenericPassword.argtypes = [ptr, u32, ctypes.c_char_p, u32,
        ctypes.c_char_p, ctypes.POINTER(u32), ctypes.POINTER(ptr), ctypes.POINTER(ptr)]
    sec.SecKeychainFindGenericPassword.restype = ctypes.c_int32
    sec.SecKeychainAddGenericPassword.argtypes = [ptr, u32, ctypes.c_char_p, u32,
        ctypes.c_char_p, u32, ptr, ctypes.POINTER(ptr)]
    sec.SecKeychainAddGenericPassword.restype = ctypes.c_int32
    sec.SecKeychainItemModifyAttributesAndData.argtypes = [ptr, ptr, u32, ptr]
    sec.SecKeychainItemModifyAttributesAndData.restype = ctypes.c_int32
    sec.SecKeychainItemFreeContent.argtypes = [ptr, ptr]
    cf.CFRelease.argtypes = [ptr]
    service, account = SERVICE.encode(), ACCOUNT.encode()
    length, content, item = u32(), ptr(), ptr()
    status = sec.SecKeychainFindGenericPassword(None, len(service), service,
        len(account), account, ctypes.byref(length), ctypes.byref(content), ctypes.byref(item))
    try:
        if data is None:
            if status == -25300:
                raise FileNotFoundError('No saved SII credentials.')
            if status != 0:
                raise RuntimeError('macOS Keychain access failed: ' + str(status))
            return ctypes.string_at(content, length.value)
        if status == 0:
            result = sec.SecKeychainItemModifyAttributesAndData(item, None, len(data), data)
        elif status == -25300:
            result = sec.SecKeychainAddGenericPassword(None, len(service), service,
                len(account), account, len(data), data, None)
        else:
            raise RuntimeError('macOS Keychain access failed: ' + str(status))
        if result != 0:
            raise RuntimeError('macOS Keychain save failed: ' + str(result))
    finally:
        if content.value:
            sec.SecKeychainItemFreeContent(None, content)
        if item.value:
            cf.CFRelease(item)


def linux_keyring():
    try:
        import keyring
    except ImportError as exc:
        raise RuntimeError('Install Python keyring and enable an OS Secret Service/KWallet backend.') from exc
    backend = keyring.get_keyring()
    name = type(backend).__module__ + '.' + type(backend).__name__
    if not any(word in name.lower() for word in ('secretservice', 'kwallet')):
        raise RuntimeError('An encrypted OS keyring backend is required; plaintext fallback is disabled.')
    return keyring


def save(payload):
    if not isinstance(payload.get('username'), str) or not payload['username'].strip():
        raise ValueError('A username is required.')
    if not isinstance(payload.get('password'), str) or not payload['password']:
        raise ValueError('A password is required.')
    data = json.dumps({'username': payload['username'], 'password': payload['password']}).encode()
    private_dir(state_dir())
    if sys.platform == 'win32':
        target = state_dir() / 'credentials.dpapi'
        temp = target.with_suffix('.tmp')
        temp.write_bytes(dpapi(data))
        temp.replace(target)
    elif sys.platform == 'darwin':
        mac_keychain(data)
    else:
        linux_keyring().set_password(SERVICE, ACCOUNT, data.decode())


def read():
    if sys.platform == 'win32':
        raw = dpapi((state_dir() / 'credentials.dpapi').read_bytes(), decrypt=True)
    elif sys.platform == 'darwin':
        raw = mac_keychain()
    else:
        raw = linux_keyring().get_password(SERVICE, ACCOUNT)
        if raw is None:
            raise FileNotFoundError('No saved SII credentials.')
    return json.loads(raw)


def status():
    backend = {'Windows': 'DPAPI CurrentUser', 'Darwin': 'macOS Keychain'}.get(platform.system(), 'OS keyring')
    if sys.platform == 'win32':
        present = (state_dir() / 'credentials.dpapi').is_file()
        return {'saved': present, 'backend': backend, 'state_dir': str(state_dir())}
    # Do not unlock a Keychain merely to inventory software. Actual read is only for login.
    return {'saved': 'check_on_login', 'backend': backend, 'state_dir': str(state_dir())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('status')
    put = sub.add_parser('save')
    put.add_argument('--stdin', action='store_true', help='Read JSON from stdin; never pass secrets as arguments.')
    get = sub.add_parser('read')
    get.add_argument('--reveal', action='store_true', required=True, help='Reveal only for the authorized CAS login.')
    args = parser.parse_args()
    try:
        if args.command == 'save':
            payload = json.load(sys.stdin) if args.stdin else {'username': input('SII username: '),
                                                              'password': getpass.getpass('SII password: ')}
            save(payload)
            print(json.dumps({'saved': True, 'backend': status()['backend']}))
        elif args.command == 'read':
            print(json.dumps(read()))
        else:
            print(json.dumps(status()))
    except FileNotFoundError:
        print(json.dumps({'error': 'credentials_missing'}))
        return 2
    except Exception as exc:
        print(json.dumps({'error': type(exc).__name__, 'message': str(exc)}))
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
