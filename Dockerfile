FROM akshshar/xr-wrl7:latest

WORKDIR /root/cwd

ARG release="XR_6.3.1+"
ENV RELEASE=$release
ARG version="0.1.0"
ENV VERSION=$version

RUN mkdir src

COPY src src
COPY build_chown.sh .
COPY app_manager.spec .

RUN tar -czvf ${VERSION}.tar.gz src/* \
    && sed -i "s/Version: 0.1.0/Version: $VERSION/g" app_manager.spec \
    && sed -i "s/Release: XR_6.3.1+/Release: $RELEASE/g" app_manager.spec \
    && mv app_manager.spec /usr/src/rpm/SPECS/app_manager.spec \
    && mv ${VERSION}.tar.gz /usr/src/rpm/SOURCES/${VERSION}.tar.gz \
    && /usr/sbin/build_rpm.sh -s /usr/src/rpm/SPECS/app_manager.spec 

CMD ["/usr/sbin/build_rpm.sh", "-s", "/usr/src/rpm/SPECS/app_manager.spec"]