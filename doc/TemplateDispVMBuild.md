Building template using Disposable VM
=====================================

Vanir builder do support building the whole template (including all the VM
components) in DispVM. This has two advantages:

1. You start with clean environment, so the build process do not depend on any
   local (potentially uncommited) changes.
2. You do not need to trust all the build scripts, including postinstallation
   scripts of installed packages, configuration scripts etc.  Note: while you
   do not need to trust those scripts during build process, this doesn't apply
   to the result package itself - if the template is compromised during build
   process, all the VMs based on this template will be compromised too. But
   only that VMs.

To use this feature you'll need to install a few Vanir RPC services:

1. In dom0:
  * `vanirbuilder.ExportDisk`
  * `vanirbuilder.AttachDisk`
2. In your VM (from where you start the build process);
  * `vanirbuilder.CopyTemplateBack`

And respective policies for them.
RPC services file are in `rpc-services` subdirectory, to install them - copy
those files to `/etc/vanir-rpc` (in dom0 for first two services, in VM for the
third one). There are also example policies to be placed in
`/etc/vanir-rpc/policy` (in dom0, for all the services) - you need to update your
devel VM name in vanirbuilder.ExportDisk and vanirbuilder.CopyTemplateBack
policy.

When you've done, you probably want to adjust some builder.conf settings. You have two options:

1. You can use the same `builder.conf` for building the template in DispVM. In
   this case you don't need to do anything.
2. You can use separate `builder.conf`, even different one for every template
   type. The `builder.conf` file can be provided using *BUILDER\_TEMPLATE\_CONF*
   setting. That variable contains space-separated list of *\<dist\>:\<location\>*
   pairs, where *<dist>* is code name of template (like `fc20`, or
   `wheezy+whonix-workstation`), and *<location>* is path to the config
   file. Alternatively you can, instead of plain path, provide git repo
   location, which contains `config/builder.conf` file. In this case *<location>*
   consists of three parameters:
   - *GIT\_URL* - full URL to some git repo
   - *BRANCH* - branch name
   - *KEY* - path to local file with key(s) to verify a tag on that repo
    Those three parameters should be separated by comas. Example:
        BUILDER_TEMPLATE_CONF = fc20+minimal:https://github.com/username/reponame,master,/home/user/keys/username.asc

That `builder.conf` should contain all the settings needed to build the template
itself. As the file will be copied alone, it should be self-contained at least
for the first *get-sources* stage (to download builder and its plugins). Then
it can include other files from builder builder plugins, if needed.

Your **original** `builder.conf` should contain settings how to package
the template, especially how it should be named (TEMPLATE\_LABEL option).

Then you can start the build process. To build all selected templates
(according to *DISTS\_VM* setting) - each in new DispVM:

    $ make template-in-dispvm

Or alternatively you can build just selected one by appending its code name:

    $ make template-in-dispvm-fc21

Details on building template in Disposable VM
---------------------------------------------
When you execute *make template-in-dispvm* it call script `scripts/build_full_template_in_dispvm`, which:

1. Create an empty disk image.
2. Mount it, copy vanir-builder there, including provided config or key to
   verify git tag.
3. Unmount that image.
4. Generate random key, associate the disk image with it
   (vanirbuilder.ExportDisk service).
5. Launch new DispVM using vanir.VMShell service, pass there a script and a key
   generated in previous step.
6. Inside the DispVM mount exported disk image (vanirbuilder.AttachDisk
   service), optionally clone repo to extract config file (of course verify git
   tag before accessing any file there).
7. Still inside DispVM, download sources according to `builder.conf` (that one
   pointed by *BUILDER\_TEMPLATE\_CONF* setting). First *builder* component is
   downloaded to possibly load some builder extensions.
8. When all the sources are downloaded, start the build process calling *make vanir-vm template*.
9. The last step is to transfer just built `root.img` and default lists of
   appmenus back to original VM (vanirbuilder.CopyTemplateBack service). This
   process uses the same key as in step 4 to authorize the transfer.
10. At this stage DispVM is destroyed, including disk image created in the first step.
11. The last step is to create rpm package to carry `root.img` and appmenus
    list. It is important to note that it doesn't parse `root.img` in any way,
    just make an archive with it.

