# Setup electrumx server with docker

## 1. Setup dashd node with docker

Used docker dashd image has `txindex=1` setting in dash.conf,
which is need by electrumx server.

Create network to link with electrumx server.

```
docker network create dash-mainnet
```

Create volume to store dashd data and settings.

```
docker volume create dashd-data
```

Start dashd container.

```
docker run --restart=always -v dashd-data:/dash \
    --name=dashd-node --net dash-mainnet -d \
    -p 9999:9999 -p 127.0.0.1:9998:9998 zebralucky/dashd
```

**Notes**:
 - port 9999 is published without bind to localhost and can be
 accessible from out world even with firewall setup:
 https://github.com/moby/moby/issues/22054

Copy or change RPC password. Random password generated
on first container startup.

```
docker exec -it dashd-node bash -l

# ... login to container

cat .dashcore/dash.conf | grep rpcpassword
```

See log of dashd.

```
docker logs dashd-node
```

## 2. Setup electrumx server with docker

Create volume to store elextrumx server data and settings.

```
docker volume create electrumx-dash-data
```

Start elextrumx container.

```
docker run --restart=always -v electrumx-dash-data:/data \
    --name electrumx-dash --net dash-mainnet -d \
    -p 50001:50001 -p 50002:50002 zebralucky/electrumx-dash:mainnet
```

Change DAEMON_URL `rpcpasswd` to password from dashd and creaate SSL cert.

**Notes**:
 - DAEMON_URL as each URL can not contain some symbols.
 - ports 50001, 50002 is published without bind to localhost and can be
 accessible from out world even with firewall setup:
 https://github.com/moby/moby/issues/22054

```
docker exec -it electrumx-dash bash -l

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

docker restart electrumx-dash
```

See log of electrumx server.

```
docker exec -it electrumx-dash bash -l

# ... login to container

tail /data/log/current

# or less /data/log/current
```

Wait some time, when electrumx sync with dashd and
starts listen on client ports. It can be seen on `/data/log/current`.
