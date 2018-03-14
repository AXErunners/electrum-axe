# Setup electrumx server with docker

## 1. Setup axed node with docker

Used docker axed image has `txindex=1` setting in axe.conf,
which is need by electrumx server.

Create network to link with electrumx server.

```
docker network create axe-mainnet
```

Create volume to store axed data and settings.

```
docker volume create axed-data
```

Start axed container.

```
docker run --restart=always -v axed-data:/axe \
    --name=axed-node --net axe-mainnet -d \
    -p 9937:9937 -p 127.0.0.1:9337:9337 axerunners/axed
```

**Notes**:
 - port 9937 is published without bind to localhost and can be
 accessible from out world even with firewall setup:
 https://github.com/moby/moby/issues/22054

Copy or change RPC password. Random password generated
on first container startup.

```
docker exec -it axed-node bash -l

# ... login to container

cat .axecore/axe.conf | grep rpcpassword
```

See log of axed.

```
docker logs axed-node
```

## 2. Setup electrumx server with docker

Create volume to store elextrumx server data and settings.

```
docker volume create electrumx-axe-data
```

Start elextrumx container.

```
docker run --restart=always -v electrumx-axe-data:/data \
    --name electrumx-axe --net axe-mainnet -d \
    -p 50001:50001 -p 50002:50002 zebralucky/electrumx-axe:mainnet
```

Change DAEMON_URL `rpcpasswd` to password from axed and creaate SSL cert.

**Notes**:
 - DAEMON_URL as each URL can not contain some symbols.
 - ports 50001, 50002 is published without bind to localhost and can be
 accessible from out world even with firewall setup:
 https://github.com/moby/moby/issues/22054

```
docker exec -it electrumx-axe bash -l

# ... login to container

cd /data/

# Edit and save env/DAEMON_URL
nano env/DAEMON_URL

# Create SSL self signed certificate

openssl genrsa -des3 -passout pass:x -out server.pass.key 2048 && \
openssl rsa -passin pass:x -in server.pass.key -out server.key && \
rm server.pass.key && \
openssl req -new -key server.key -out server.csr

openssl x509 -req -days 730 -in server.csr -signkey server.key \
  -out server.crt && rm server.csr


exit
# ... logout from container

# Restart electrumx container to switch on new RPC password

docker restart electrumx-axe
```

See log of electrumx server.

```
docker exec -it electrumx-axe bash -l

# ... login to container

tail /data/log/current

# or less /data/log/current
```

Wait some time, when electrumx sync with axed and
starts listen on client ports. It can be seen on `/data/log/current`.
