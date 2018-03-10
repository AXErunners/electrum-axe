test -d x11_hash || git clone https://github.com/akhavr/x11_hash
(cd x11_hash; git checkout 1.4)

cat  > ./.build-x11_hash.sh <<EOF
cd /opt/x11_hash; wine python setup.py build
EOF

docker run --rm -t --privileged -v $(pwd):/opt \
       -e WINEPREFIX="/wine/wine-py2.7.8-32" \
       ogrisel/python-winbuilder \
       sh /opt/.build-x11_hash.sh
