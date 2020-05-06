FROM akshshar/xr-wrl7:latest

WORKDIR /root/cwd
ARG version="0.1.0"

ENV VERSION=$version

COPY . .

RUN ls -la \
    && rm -rf build/* \
    && rm -rf RPMS/* \
    && rm -rf ${VERSION}.tar.gz > /dev/null 2>&1 \
    && cd build && tar -czvf ${VERSION}.tar.gz ../src/*

WORKDIR /root/cwd

RUN ./build_chown.sh root root \
    && sed -i "s/Version: 0.1.0/Version: $VERSION/g" app_manager.spec \
    && mv app_manager.spec /usr/src/rpm/SPECS/app_manager.spec \
    && mv build/${VERSION}.tar.gz /usr/src/rpm/SOURCES/${VERSION}.tar.gz \
    && mv build/ /tmp/ \
    && /usr/sbin/build_rpm.sh -s /usr/src/rpm/SPECS/app_manager.spec 

CMD ["/usr/sbin/build_rpm.sh", "-s", "/usr/src/rpm/SPECS/app_manager.spec"]