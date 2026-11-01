"""Initialize PXVIRT's management certificate and reload its web service."""
import subprocess


def main():
    subprocess.run(['pvecm', 'updatecerts', '--silent'], check=True, timeout=180,
                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    subprocess.run(['systemctl', 'reload-or-restart', 'pveproxy.service'],
                   check=True, timeout=180, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    print('PXVIRT management service initialized')


if __name__ == '__main__':
    main()
